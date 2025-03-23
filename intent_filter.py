import sqlite3
import numpy as np
import json
import logging
import datetime
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from context_loader import build_prompt_context, load_accounts, load_bills
from dotenv import load_dotenv
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("intent_filter.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

OPENAI_API_KEY = os.getenv("OPEN_AI_API_KEY")
DB_PATH = "firefly_local.db"

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize the sentence-transformers model
model = SentenceTransformer('all-MiniLM-L6-v2')

def load_account_cache():
    """Load account names/IDs from SQLite into a dict."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, name, type FROM accounts")
    account_cache = {name.lower(): {"id": acc_id, "type": acc_type}
                     for acc_id, name, acc_type in cur.fetchall()}
    conn.close()
    return account_cache

account_cache = load_account_cache()

def find_similar_transactions(desc, top_k=3):
    """Find the top-k most similar transactions by embedding similarity."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    embedding = model.encode(desc)

    cur.execute("SELECT transaction_id, embedding FROM transaction_embeddings")
    rows = cur.fetchall()
    similarities = []
    for tid, emb in rows:
        try:
            emb_array = np.frombuffer(emb, dtype=np.float32)
            similarity = cosine_similarity([embedding], [emb_array])[0][0]
            similarities.append((tid, similarity))
        except Exception as e:
            logger.error(f"Error processing embedding for transaction {tid}: {e}")

    conn.close()
    similarities.sort(key=lambda x: x[1], reverse=True)
    return similarities[:top_k]

def extract_tags_from_input(user_input):
    """
    Extract tags from the user input if specified in the format 'tags:tag1,tag2'.
    Returns a list of tags and the cleaned input without the 'tags:' section.
    """
    if "tags:" in user_input:
        parts = user_input.split("tags:")
        main_input = parts[0].strip()
        tags_part = parts[1].strip()
        tags = [tag.strip().lower() for tag in tags_part.split(",") if tag.strip()]
        return main_input, tags
    return user_input, []

def determine_intent(user_input):
    # Extract user-specified tags
    user_input, user_tags = extract_tags_from_input(user_input)

    # 1) Fetch the dynamic context snippet
    context_snippet = build_prompt_context()
    
    # 2) Pull context from the top similar transaction
    similar_tids = find_similar_transactions(user_input, top_k=1)
    context_info = {
        "previous_description": "",
        "typical_amount": "",
        "common_source": "",
        "common_destination": "",
        "common_category": "",
        "common_tags": []
    }

    if similar_tids:
        best_tid = similar_tids[0][0]
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT t.description, t.amount, t.source_name, t.destination_name, t.category_name
            FROM transactions t
            WHERE t.id = ?
        """, (best_tid,))
        row = cur.fetchone()

        cur.execute("SELECT name FROM transactions_tags WHERE transaction_id = ?", (best_tid,))
        tag_rows = cur.fetchall()
        conn.close()

        if row:
            context_info["previous_description"] = row[0]
            context_info["typical_amount"] = str(row[1])
            context_info["common_source"] = row[2]
            context_info["common_destination"] = row[3]
            context_info["common_category"] = row[4]
        if tag_rows:
            context_info["common_tags"] = [t[0] for t in tag_rows]

    # 3) Build prompt. 
    # Dynamically include similar transaction context
    similar_context = ""
    if similar_tids:
        best_tid = similar_tids[0][0]
        similar_context = f"""
        - previous_description: {context_info['previous_description']}
        - typical_amount: {context_info['typical_amount']}
        - common_source: {context_info['common_source']}
        - common_destination: {context_info['common_destination']}
        - common_category: {context_info['common_category']}
        - common_tags: {context_info['common_tags']}
        """

    prompt = f"""
        You are a finance assistant that generates a structured Firefly III transaction.

        -----------

        ## FINAL Firefly Payload Format:

        payload = {{
        "transactions": [
            {{
                "type": "(string: 'bill'|'withdrawal'|'transfer'|'deposit')",
                "amount": "(string or number)",
                "description": "(short descriptive text)",
                "source_id": "(number, or unknown if not inferred)",
                "destination_id": "(number, or unknown if not inferred)",
                "currency_code": "(string, e.g. 'JPY' or 'USD')",
                "date": "(string: 'YYYY-MM-DD', always use today's date from Python)",
                "category_name": "(string)",
                "bill_id": "(number, or unknown if not a bill payment)",
                "tags": "(array of strings, relevant to the transaction, e.g., 'shopping', 'amazon')",
                "notes": "Created by Firefly Assistant"
            }}
        ]
        }}

        -----------

        ## KNOWN ACCOUNTS:
        These are the user’s existing Firefly accounts (name → ID). If the user input references any of these names (case-insensitive), set the matching ID accordingly.

        {context_snippet}

        -----------

        ## INPUT DATA:

        1) **User message**:
        {user_input}

        2) **Similar transaction context**:
        {similar_context}
        -----------

        ## INSTRUCTIONS:

        1) Determine "type" from user context:
        - "withdrawal" if expense or bill
        - "deposit" if money in
        - "transfer" if moving between personal accounts

        2) If the user doesn't specify "amount" or "source_id"/"destination_id", try to infer from context or from the known accounts list. If still unknown, mark them in "missing_info".
        - "withdrawal" and bill usually only have source id
        - "deposit" usually only have destination id
        - "transfer" has both

        3) "currency_code":
        - "JPY" if user says "yen"
        - "USD" if user says "dollar" or if uncertain

        4) "description":
        - Make it more descriptive than the user’s raw input if possible.
        - Possibly incorporate context from "previous_description".

        5) "tags":
        - Always include user-specified tags: {user_tags}.
        - If no user-specified tags, use only tags from "KNOWN TAGS" (strict matching).

        6) "category_name":
        - If user or context suggests a category, fill it in. Else, can remain empty.

        7) "notes":
        - Always "Created by Firefly Assistant".

        8) "date":
        - Always use today's date from Python.

        9) "bill_id":
        - If the transaction is a bill payment, include the bill ID stricly from the known bills list.

        9) Output must be a **valid JSON** object with exactly these top-level keys:
        {{
            "type": "string",
            "amount": "string",
            "description": "string",
            "source_id": "string or number",
            "destination_id": "string or number",
            "currency_code": "string",
            "date": "string (YYYY-MM-DD)",
            "category_name": "string",
            "tags": ["array","of","strings"],
            "missing_info": ["array","of","strings"],
            "bill_id": "string or number"
        }}

        NOTE: "missing_info" is for any fields you truly cannot infer.
        If "source_id" is unknown, put "source_id" in there, etc.

        Return ONLY that JSON object, with NO extra keys.

        Example valid output:
        {{
        "type": "deposit",
        "amount": "1000",
        "description": "Topup to PayPay account",
        "source_id": 1,
        "destination_id": 16,
        "currency_code": "USD",
        "date": "2023-10-05",
        "category_name": "Topup",
        "tags": ["paypay", "foramazon"],
        "missing_info": []
        }}

        -----------

        ## TASK:
        Return exactly one JSON object following the specification above.
    """

    # 3) Call OpenAI
    logger.info("Prompt to LLM:\n%s", prompt)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # or your chosen model name
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4
        )
        response_str = response.choices[0].message.content.strip()
        logger.info(f"Raw LLM response: {response_str}")
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return None

    # 4) Parse the JSON
    try:
        data = json.loads(response_str)
    except json.JSONDecodeError:
        logger.error("LLM did not return valid JSON.")
        return None

    # 5) Extract & finalize
    missing_info = data.get("missing_info", [])
    if not isinstance(missing_info, list):
        missing_info = []

    # Always use today's date
    date_str = datetime.date.today().isoformat()

    # Load account mapping
    account_map = load_accounts()
    logger.info(f"Loaded account map: {account_map}")

    # Load bill mapping
    bill_map = load_bills()
    bill_id = str(data.get("bill_id", "unknown")).lower()
    logger.info(f"Loaded bill map: {bill_map}")

    # Debugging source_id and destination_id
    source_id = str(data.get("source_id", "unknown")).lower()
    destination_id = str(data.get("destination_id", "unknown")).lower()
    logger.info(f"Source ID: {source_id}, Destination ID: {destination_id}")

    # Return a dictionary with consistent keys
    result = {
        "type": data.get("type", "withdrawal"),
        "amount": str(data.get("amount", "0")),
        "description": data.get("description", user_input),
        "source_id": data.get("source_id", "unknown"),
        "destination_id": data.get("destination_id", "unknown"),
        "source_name": account_map.get(source_id, ""),
        "destination_name": account_map.get(destination_id, ""),
        "currency_code": data.get("currency_code", "USD"),
        "date": date_str,
        "category_name": data.get("category_name", ""),
        "tags": list(set(user_tags + data.get("tags", []))),  # Combine user-specified and GPT-generated tags
        "bill_name": bill_map.get(bill_id, {}).get("name", ""),
        "bill_id": data.get("bill_id", "unknown"),
        "missing_info": missing_info
    }

    logger.info(f"Parsed transaction proposal: {result}")
    return result

if __name__ == "__main__":
    # Quick test
    test_input = "Pay 768 yen at Sukiya"
    proposal = determine_intent(test_input)
    print("Final proposal:", proposal)
