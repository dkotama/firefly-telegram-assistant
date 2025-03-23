import logging
from dotenv import load_dotenv
import os
import sqlite3

from intent_filter import find_similar_transactions, DB_PATH as INTENT_DB_PATH
from firefly_sync import DB_PATH as SYNC_DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("similarity_test.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()
DB_PATH = SYNC_DB_PATH

TEST_CASES = [
    {"input": "Topped up PayPay from Yucho", "expected_id": "146", "description": "Should match 'Topup PayPay' (ID 146)"},
    {"input": "PayPay topup", "expected_id": "146", "description": "Should suggest Yucho as source for 'Topup PayPay' (ID 146)"},
    {"input": "Recharged PayPay with Yucho", "expected_id": "146", "description": "Should match 'Topup PayPay' with synonym (ID 146)"},
    {"input": "Safety box with PayPay", "expected_id": "148", "description": "Should match 'Safety Box' (ID 148)"},
    {"input": "Bought safety box", "expected_id": "148", "description": "Should suggest PayPay as source for 'Safety Box' (ID 148)"},
    {"input": "Pak Surya debt from Yucho", "expected_id": "161", "description": "Should match 'Bayar Hutang ke Pak Surya' (ID 161)"},
    {"input": "Paid Pak Surya", "expected_id": "161", "description": "Should suggest Yucho as source for 'Bayar Hutang ke Pak Surya' (ID 161)"},
]

def run_tests():
    logger.info("Starting similarity tests using existing database: %s", DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for tid in ["146", "148", "161"]:
        cur.execute("SELECT description, category_id, source_name, destination_name FROM transactions WHERE id = ?", (tid,))
        result = cur.fetchone()
        if result:
            logger.info("Transaction ID %s found: description=%s, category_id=%s, source=%s, destination=%s", tid, *result)
        else:
            logger.warning("Transaction ID %s not found in database!", tid)
    conn.close()

    for test in TEST_CASES:
        logger.info("Testing input: %s", test["input"])
        logger.info("Expectation: %s", test["description"])
        
        similar_tids = find_similar_transactions(test["input"])
        top_match = similar_tids[0] if similar_tids else None
        
        if top_match:
            tid, similarity = top_match
            logger.info("Top match: transaction_id=%s, similarity=%.4f", tid, similarity)
            
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                SELECT t.description, t.source_name, t.destination_name, t.category_name, t.type,
                       GROUP_CONCAT(tt.name, ', ') AS tags, t.amount
                FROM transactions t
                LEFT JOIN transactions_tags tt ON t.id = tt.transaction_id
                WHERE t.id = ?
                GROUP BY t.id
            """, (tid,))
            matched_tx = cur.fetchone()
            if matched_tx:
                desc, src, dest, cat, typ, tags, amount = matched_tx
                logger.info("Matched details: description=%s, source=%s, destination=%s, category=%s, type=%s, tags=%s, amount=%s",
                            desc, src, dest, cat, typ, tags, amount)
            conn.close()

            if tid == test["expected_id"]:
                logger.info("[PASS] Test passed: Correct transaction found.")
            else:
                logger.info("[FAIL] Test failed: Expected transaction_id=%s, got=%s", test["expected_id"], tid)
        else:
            logger.info("[FAIL] Test failed: No similar transactions found.")
    logger.info("Similarity tests complete.")

if __name__ == "__main__":
    run_tests()