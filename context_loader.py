# context_loader.py

import sqlite3
from typing import Dict, List
import logging

DB_PATH = "firefly_local.db"

def load_accounts() -> Dict[str, str]:
    """
    Load accounts from the local Firefly DB and return a dict mapping
    account ID (as a string) -> account name.
    For example: {"12": "wallet cash", "15": "cash account", "20": "savings"}.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Load asset accounts only
    cur.execute("""
        SELECT id, name 
        FROM accounts
        WHERE type IN ('asset')
        ORDER BY name
    """)
    rows = cur.fetchall()
    conn.close()

    # Build the mapping
    account_map = {}
    for (acc_id, acc_name) in rows:
        # Key: account ID as a string, Value: account name
        account_map[str(acc_id)] = acc_name

    # Log the loaded accounts for debugging
    logging.info(f"Loaded accounts: {account_map}")
    return account_map

def load_categories() -> List[str]:
    """
    Return a simple list of all category names from the local DB, if you want
    them for context as well.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM categories ORDER BY name")
    rows = cur.fetchall()
    conn.close()

    categories = [r[0] for r in rows if r[0]]
    return categories

def load_tags() -> List[str]:
    """
    Return a simple list of all unique tags from the transactions_tags table.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT name FROM transactions_tags ORDER BY name")
    rows = cur.fetchall()
    conn.close()

    tags = [r[0] for r in rows if r[0]]
    return tags

def load_bills() -> Dict[int, Dict]:
    """Return a dict mapping bill ID to bill details."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name
        FROM bills
        ORDER BY name
    """)
    rows = cur.fetchall()
    conn.close()

    bills_map = {}
    for (bill_id, name) in rows:
        bills_map[bill_id] = {
            "name": name,
        }

    logging.info(f"Loaded bills: {bills_map}")
    return bills_map

def build_prompt_context() -> str:
    """
    Construct a text snippet containing known accounts, categories, tags, and bills
    that you can embed in your LLM prompt.
    """
    account_map = load_accounts()
    categories = load_categories()
    tags = load_tags()
    bills = load_bills()

    # Accounts section
    accounts_section = "## KNOWN ACCOUNTS:\n"
    if account_map:
        for acc_id, name in account_map.items():
            accounts_section += f'  - "{name}" → {acc_id}\n'
    else:
        accounts_section += "  (No accounts found.)\n"

    # Categories section
    categories_section = "## KNOWN CATEGORIES:\n"
    if categories:
        for cat in categories:
            categories_section += f"  - {cat}\n"
    else:
        categories_section += "  (No categories found.)\n"

    # Tags section
    tags_section = "## KNOWN TAGS:\n"
    if tags:
        for tag in tags:
            tags_section += f"  - {tag}\n"
    else:
        tags_section += "  (No tags found.)\n"

    # Bills section
    bills_section = "## KNOWN BILLS:\n"
    if bills:
        for bill_id, details in bills.items():
            bills_section += f'  - "{details["name"]}" → {bill_id}\n'
    else:
        bills_section += "  (No bills found.)\n"

    # Return the combined text
    return f"{accounts_section}\n{categories_section}\n{tags_section}\n{bills_section}"

if __name__ == "__main__":
    # Quick test
    print("=== Testing context_loader ===")
    print("Loaded Accounts:", load_accounts())
    print("Loaded Categories:", load_categories())
    print("Loaded Tags:", load_tags())
    print("Loaded Bills:", load_bills())
    print("\nFull Prompt Context:\n")
    print(build_prompt_context())