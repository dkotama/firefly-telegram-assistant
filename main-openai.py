import os
import re
import json
import asyncio
import subprocess
import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from openai import OpenAI

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FIREFLY_API_TOKEN = os.getenv("FIREFLY_API_TOKEN")
FIREFLY_API_URL = os.getenv("FIREFLY_API_URL")
OPENAI_API_KEY = os.getenv("OPEN_AI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

########################################
# 1. Firefly III API helper
########################################

def call_firefly_api_curl(endpoint, method="GET", data=None):
    url = f"{FIREFLY_API_URL.rstrip('/')}" + "/" + endpoint.lstrip('/')
    token = FIREFLY_API_TOKEN
    curl_cmd = [
        "curl", "-X", method, url,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Accept: application/json"
    ]
    if method == "POST" and data:
        curl_cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    result = subprocess.run(curl_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[Firefly API Error] {result.stderr}")
        return None
    raw_response = result.stdout
    print("[Firefly API Response]", raw_response)
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        print("[Firefly API Warning] Failed to parse JSON:", raw_response)
        return raw_response

########################################
# 2. Utility for parsing multiline key-value
########################################
def parse_key_value_response(response_text: str) -> dict:
    """Parses a multiline key=value response into a dict. Ignores lines without '='."""
    result = {}
    for line in response_text.strip().splitlines():
        if '=' in line:
            key, val = line.split('=', 1)
            result[key.strip()] = val.strip()
    return result

########################################
# 3. Single GPT Prompt that returns multiline key=val
########################################
import difflib

async def parse_financial_message(user_input: str, accounts_str: str, update: Update):
    """
    Single GPT call that returns all needed fields (type, amount, currency, source_id, destination_id, etc.)
    in a multiline key-value format. e.g.:
      type=withdrawal\namount=500\n...
    We'll also print the prompt to the user for debugging.
    """
    today = datetime.date.today().isoformat()

    prompt = f"""
You are a finance assistant. A user wrote this message: "{user_input}".
We have these known Firefly accounts (id, name, type, currency):
{accounts_str}

Output multiline key=value pairs, one per line, with no extra text, using these keys:
- type (withdrawal|deposit|transfer)
- description
- amount
- currency_code
- category_name
- source_id
- destination_id
- tags (comma-separated if multiple)
- date

Rules:
- If user text suggests paying rent for 'apato', use tags like "housing,rent" and category "Housing".
- If user text suggests restaurant/food (like sukiya), use tags like "food" and category "Food".
- If user text indicates a deposit or income, set type=deposit.
- If user text is a "bill", set type=withdrawal and add "bill" to tags.
- For withdrawals: source=asset, destination=expense.
- For deposits: source=revenue/asset, destination=asset.
- For transfers: source=asset, destination=asset.
- If no match for user-specified account, guess the best or use "0".
- If currency is unknown, default to "USD".
- Use today's date {today} for date.

Example:
  type=withdrawal\ndescription=Apartment Payment\namount=30000\ncurrency_code=USD\ncategory_name=Housing\nsource_id=? (an asset account id)\ndestination_id=? (an expense account id)\ntags=housing,rent\ndate={today}

"""

    # Print the prompt to console
    print("[GPT Prompt]", prompt)
    # Optionally, also show it to the user (shortened if needed)
    short_prompt = (prompt[:4000] + '...') if len(prompt) > 4000 else prompt
    await update.message.reply_text(f"[DEBUG] Prompt sent to GPT:\n{short_prompt}")

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        content = response.choices[0].message.content.strip()
        print("[GPT Raw Response]", content)

        # Now parse the multiline key=val
        data = parse_key_value_response(content)
        return data
    except Exception as e:
        print("[GPT Error]", str(e))
        return None

########################################
# 4. Telegram Bot Logic
########################################

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()

    # 4a) Fetch Firefly accounts
    accounts_response = call_firefly_api_curl("/accounts?type=asset,expense,revenue")
    if not accounts_response or "data" not in accounts_response:
        await update.message.reply_text("❌ Could not fetch accounts from Firefly.")
        return

    # Build an easy-to-use text list for GPT
    accounts_list = []
    for account_item in accounts_response["data"]:
        aid = account_item["id"]
        attrs = account_item["attributes"]
        name = attrs["name"]
        atype = attrs["type"]
        currency = attrs["currency_code"]
        accounts_list.append(f"id:{aid},name:{name},type:{atype},currency:{currency}")

    # Show user the known accounts for clarity
    if accounts_list:
        preview_accounts = "\n".join(accounts_list)
        await update.message.reply_text(f"[DEBUG] We have {len(accounts_list)} Firefly accounts:\n{preview_accounts}")
    else:
        await update.message.reply_text("[DEBUG] No Firefly accounts found.")

    accounts_str = "\n".join(accounts_list)

    # 4b) Single GPT call to parse user input
    parsed = await parse_financial_message(user_input, accounts_str, update)
    if not parsed:
        await update.message.reply_text("❌ Failed to parse your message.")
        return

    # 4c) Validate the GPT response
    required_keys = ["type", "amount", "description", "currency_code", "source_id", "destination_id", "date"]
    for k in required_keys:
        if k not in parsed:
            await update.message.reply_text(f"❌ Missing field '{k}' in GPT response.")
            return

    amount = parsed.get("amount", "").strip()
    src_id = parsed.get("source_id", "").strip()
    dst_id = parsed.get("destination_id", "").strip()
    if not amount or amount in ["0", "unknown"]:
        await update.message.reply_text("❌ No valid amount. Please specify the amount.")
        return
    # 0 means GPT couldn't find a matching account
    if src_id == "0" or dst_id == "0":
        await update.message.reply_text("⚠️ GPT set an account to '0'. You may want to correct or specify the right account.")

    # 4d) Build transaction payload
    # For tags, GPT might output them as comma-separated in 'tags'
    raw_tags = parsed.get("tags", "").strip()
    tags_list = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []

    transaction_payload = {
        "transactions": [
            {
                "type": parsed.get("type", "withdrawal"),
                "amount": amount,
                "description": parsed.get("description", ""),
                "category_name": parsed.get("category_name", ""),
                "source_id": src_id,
                "destination_id": dst_id,
                "currency_code": parsed.get("currency_code", "USD"),
                "date": parsed.get("date", datetime.date.today().isoformat()),
                "tags": tags_list
            }
        ]
    }

    # 4e) Show preview
    t = transaction_payload["transactions"][0]
    preview = (f"[Transaction Preview]\n"\
               f"Type: {t['type']}\n"\
               f"Amount: {t['amount']}\n"\
               f"Description: {t['description']}\n"\
               f"Category: {t['category_name']}\n"\
               f"Source ID: {t['source_id']}\n"\
               f"Destination ID: {t['destination_id']}\n"\
               f"Currency: {t['currency_code']}\n"\
               f"Date: {t['date']}\n"\
               f"Tags: {', '.join(t['tags'])}")
    await update.message.reply_text(preview)

    # 4f) Post to Firefly
    response = call_firefly_api_curl("/transactions", method="POST", data=transaction_payload)
    if response and "data" in response:
        await update.message.reply_text("✅ Transaction posted successfully!")
    else:
        await update.message.reply_text("❌ Failed to post transaction.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hi! Send me an expense like '768 yen sukiya' or '30000 apato rent'!")


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Bot running. Send it a message!")
    app.run_polling()

if __name__ == "__main__":
    main()
