#!/usr/bin/env python3

import os
import json
import sqlite3
import subprocess
from dotenv import load_dotenv
import logging
from sentence_transformers import SentenceTransformer

load_dotenv()

FIREFLY_API_TOKEN = os.getenv("FIREFLY_API_TOKEN")
FIREFLY_API_URL = os.getenv("FIREFLY_API_URL")
DB_PATH = "firefly_local.db"

logging.basicConfig(filename="firefly_sync.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def call_firefly_api_curl(endpoint, method="GET", data=None):
    url = f"{FIREFLY_API_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    token = FIREFLY_API_TOKEN
    curl_cmd = ["curl", "-X", method, url, "-H", f"Authorization: Bearer {token}", "-H", "Accept: application/json"]
    if method == "POST" and data:
        payload = json.dumps(data)
        curl_cmd += ["-H", "Content-Type: application/json", "-d", payload]
        logging.debug(f"POST Payload: {payload}")  # Log the payload

    logging.debug(f"Executing API call: {' '.join(curl_cmd)}")
    logging.debug(f"CURL Command: {curl_cmd}")
    
    result = subprocess.run(curl_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"API call failed with error: {result.stderr}")
        return None

    logging.debug(f"API Response: {result.stdout}")  # Log the response
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        logging.error(f"Failed to parse API response: {result.stdout}")
        return None

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute('''
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY,
        name TEXT,
        type TEXT,
        currency TEXT,
        last_updated TEXT
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY,
        name TEXT,
        last_updated TEXT
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS bills (
        id INTEGER PRIMARY KEY,
        name TEXT,
        amount_min REAL,
        amount_max REAL,
        last_updated TEXT
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        description TEXT,
        amount REAL,
        created_at TEXT,  -- Renamed from date to match API
        source_id INTEGER,
        destination_id INTEGER,
        category_id INTEGER,
        type TEXT,
        source_name TEXT,
        destination_name TEXT,
        category_name TEXT,
        last_updated TEXT
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS transactions_tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER,
        name TEXT,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS transaction_embeddings (
        transaction_id INTEGER PRIMARY KEY,
        embedding BLOB,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    )
    ''')

    conn.commit()
    conn.close()

# Sync accounts (unchanged)
def sync_accounts(last_sync_time=None):
    logging.info("Fetching accounts from Firefly...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    page = 1
    total_changes = 0
    
    while True:
        endpoint = f"/accounts?type=asset,expense,revenue&page={page}"
        if last_sync_time:
            endpoint += f"&updated_at={last_sync_time}"
        data = call_firefly_api_curl(endpoint)
        if not data or "data" not in data:
            logging.error("No valid account data returned.")
            break

        page_data = data["data"]
        if not page_data:
            logging.info(f"No more accounts to fetch at page {page}.")
            break

        for item in page_data:
            acc_id = int(item["id"])
            attrs = item["attributes"]
            name = attrs.get("name", "")
            acc_type = attrs.get("type", "")
            currency = attrs.get("currency_code", "")
            last_updated = attrs.get("updated_at", "")

            if acc_type in ["reconciliation", "initial-balance"]:
                continue

            result = cur.execute('''
                INSERT OR REPLACE INTO accounts (id, name, type, currency, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (acc_id, name, acc_type, currency, last_updated))
            total_changes += result.rowcount

        conn.commit()
        page += 1

    conn.close()
    logging.info(f"Accounts synced. Total inserted/updated: {total_changes}")

# Sync categories (unchanged)
def sync_categories(last_sync_time=None):
    logging.info("Fetching categories...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    page = 1
    total_changes = 0
    
    while True:
        endpoint = f"/categories?page={page}"
        if last_sync_time:
            endpoint += f"&updated_at={last_sync_time}"
        data = call_firefly_api_curl(endpoint)
        if not data or "data" not in data:
            logging.error("No valid category data returned.")
            break

        page_data = data["data"]
        if not page_data:
            logging.info(f"No more categories to fetch at page {page}.")
            break

        for item in page_data:
            cat_id = int(item["id"])
            attrs = item["attributes"]
            name = attrs.get("name", "")
            last_updated = attrs.get("updated_at", "")

            result = cur.execute('''
                INSERT OR REPLACE INTO categories (id, name, last_updated)
                VALUES (?, ?, ?)
            ''', (cat_id, name, last_updated))
            total_changes += result.rowcount

        conn.commit()
        page += 1

    conn.close()
    logging.info(f"Categories synced. Total inserted/updated: {total_changes}")

# Sync bills (unchanged)
def sync_bills(last_sync_time=None):
    logging.info("Fetching bills...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    page = 1
    total_changes = 0
    
    while True:
        endpoint = f"/bills?page={page}"
        if last_sync_time:
            endpoint += f"&updated_at={last_sync_time}"
        data = call_firefly_api_curl(endpoint)
        if not data or "data" not in data:
            logging.error("No valid bill data returned.")
            break

        page_data = data["data"]
        if not page_data:
            logging.info(f"No more bills to fetch at page {page}.")
            break

        for item in page_data:
            bill_id = int(item["id"])
            attrs = item["attributes"]
            name = attrs.get("name", "")
            amount_min = float(attrs.get("amount_min", 0.0))
            amount_max = float(attrs.get("amount_max", 0.0))
            last_updated = attrs.get("updated_at", "")

            result = cur.execute('''
                INSERT OR REPLACE INTO bills (id, name, amount_min, amount_max, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (bill_id, name, amount_min, amount_max, last_updated))
            total_changes += result.rowcount

        conn.commit()
        page += 1

    conn.close()
    logging.info(f"Bills synced. Total inserted/updated: {total_changes}")

def sync_transactions(last_sync_time=None):
    logging.info("Fetching transactions...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    page = 1
    total_changes = 0
    
    while True:
        endpoint = f"/transactions?page={page}"
        if last_sync_time:
            endpoint += f"&updated_at={last_sync_time}"
        data = call_firefly_api_curl(endpoint)
        if not data or "data" not in data:
            logging.error("No valid transaction data returned.")
            break

        page_data = data["data"]
        if not page_data:
            logging.info(f"No more transactions to fetch at page {page}.")
            break

        for item in page_data:
            trans_id = int(item["id"])
            attrs = item["attributes"]
            trans = attrs["transactions"][0]
            description = trans.get("description", "")
            amount = float(trans.get("amount", 0.0))
            created_at = attrs.get("created_at", "")  # Fixed: Use created_at from attrs
            source_id = int(trans.get("source_id", 0)) or None
            destination_id = int(trans.get("destination_id", 0)) or None
            cat_val = trans.get("category_id")
            if cat_val is not None:
                category_id = int(cat_val)
            else:
                category_id = None
            trans_type = trans.get("type", "withdrawal")
            source_name = trans.get("source_name", "")
            destination_name = trans.get("destination_name", "")
            category_name = trans.get("category_name", "")
            last_updated = attrs.get("updated_at", "")
            tags = trans.get("tags", []) or []

            logging.info(f"Transaction {trans_id} tags: {tags}")

            result = cur.execute('''
                INSERT OR REPLACE INTO transactions (
                    id, description, amount, created_at, source_id, destination_id, category_id, type,
                    source_name, destination_name, category_name, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (trans_id, description, amount, created_at, source_id, destination_id, category_id, trans_type,
                  source_name, destination_name, category_name, last_updated))
            total_changes += result.rowcount

            for tag in tags:
                if tag:
                    logging.info(f"Inserting tag '{tag}' for transaction {trans_id}")
                    cur.execute("INSERT INTO transactions_tags (transaction_id, name) VALUES (?, ?)", 
                                (trans_id, tag))

        conn.commit()
        page += 1

    conn.close()
    logging.info(f"Transactions synced. Total inserted/updated: {total_changes}")

# ... (rest of the file unchanged)


# ... (rest of file unchanged)

def store_transaction_embeddings():
    logging.info("Loading pretrained SentenceTransformer: all-MiniLM-L6-v2")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total_changes = 0
    
    cur.execute("""
        SELECT t.id, t.description, t.source_name, t.destination_name, t.category_name,
               GROUP_CONCAT(tt.name, ', ') AS tags, t.amount
        FROM transactions t
        LEFT JOIN transactions_tags tt ON t.id = tt.transaction_id
        WHERE t.id NOT IN (SELECT transaction_id FROM transaction_embeddings)
        GROUP BY t.id, t.description, t.source_name, t.destination_name, t.category_name
    """)
    rows = cur.fetchall()
    for trans_id, desc, src_name, dest_name, cat_name, tags, amount in rows:
        parts = [desc or ""]
        if src_name:
            parts.append(f"source {src_name}")  # Emphasize source
            parts.append(f"from {src_name}")
        if dest_name:
            parts.append(f"destination {dest_name}")  # Emphasize destination
            parts.append(f"to {dest_name}")
        if cat_name:
            parts.append(f"category {cat_name}")
        if tags:
            parts.append(f"tags {tags}")
        if amount:
            parts.append(f"amount {amount}")
        embedding_text = " ".join(parts)
        logging.info(f"Embedding text for transaction {trans_id}: {embedding_text}")
        embedding = model.encode(embedding_text).tobytes()
        result = cur.execute("INSERT OR REPLACE INTO transaction_embeddings (transaction_id, embedding) VALUES (?, ?)", 
                             (trans_id, embedding))
        total_changes += result.rowcount
    
    conn.commit()
    conn.close()
    logging.info(f"Transaction embeddings stored. Total inserted/updated: {total_changes}")

# ... (rest of file unchanged)
# ... (rest of the file unchanged)

def main():
    logging.info("Starting Firefly sync...")
    last_sync_time = "2025-01-01T00:00:00Z"
    init_db()
    sync_accounts(last_sync_time)
    sync_categories(last_sync_time)
    sync_bills(last_sync_time)
    sync_transactions(last_sync_time)
    store_transaction_embeddings()
    logging.info("Sync complete!")

if __name__ == "__main__":
    main()