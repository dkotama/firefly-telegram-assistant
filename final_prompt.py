import subprocess
import json
import datetime
from dotenv import load_dotenv
import os

load_dotenv()

FIREFLY_API_TOKEN = os.getenv("FIREFLY_API_TOKEN")
FIREFLY_API_URL = os.getenv("FIREFLY_API_URL")

def call_firefly_api_curl(endpoint, method="GET", data=None):
    """Make an API call to Firefly III using curl."""
    url = f"{FIREFLY_API_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    token = FIREFLY_API_TOKEN
    curl_cmd = ["curl", "-X", method, url, "-H", f"Authorization: Bearer {token}", "-H", "Accept: application/json"]
    if method == "POST" and data:
        curl_cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    result = subprocess.run(curl_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return None
    return json.loads(result.stdout) if result.stdout else None

def process(proposal):
    """Generate and send the final transaction payload to Firefly III."""
    payload = {
        "transactions": [
            {
                "type": proposal["intent"],
                "amount": proposal["amount"],
                "description": proposal["description"],
                "source_id": proposal["source_id"],
                "destination_id": proposal["destination_id"],
                "currency_code": "JPY" if proposal["currency"] == "yen" else "USD",
                "date": datetime.date.today().isoformat(),
                "category_name": proposal.get("category_name", ""),
                "bill_id": proposal["bill_id"],
                "tags": proposal.get("tags", [])
            }
        ]
    }
    response = call_firefly_api_curl("/transactions", "POST", payload)
    return response and "data" in response

if __name__ == "__main__":
    # Test payload
    test_proposal = {
        "intent": "withdrawal",
        "description": "Sukiya expense",
        "amount": "768",
        "currency": "yen",
        "source": "wallet cash",
        "destination": "Sukiya",
        "source_id": "12",  # Adjust based on your accounts
        "destination_id": "0",  # Sukiya might not be an account; adjust logic if needed
        "category_name": "",
        "tags": []
    }
    success = process(test_proposal)
    print("Success:", success)