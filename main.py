import os
import json
import logging
import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    ContextTypes, filters
)

import sqlite3

import intent_filter  # the updated file above
from firefly_sync import call_firefly_api_curl  # Import the function

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FIREFLY_API_URL = os.getenv("FIREFLY_API_URL")
FIREFLY_API_TOKEN = os.getenv("FIREFLY_API_TOKEN")
AUTHORIZED_USERS = set(map(int, os.getenv("AUTHORIZED_USERS", "").split(","))) if os.getenv("AUTHORIZED_USERS") else set()

logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

# Simple account fetch for menu:
def fetch_accounts():
    """Return a list of (account_id, account_name) from local DB for assets only."""
    conn = sqlite3.connect("firefly_local.db")
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM accounts ORDER BY name ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def is_user_authorized(user_id: int) -> bool:
    """Check if the user is in the authorized list."""
    return user_id in AUTHORIZED_USERS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not is_user_authorized(update.effective_user.id):
        return  # Do not respond if the user is not authorized
    await update.message.reply_text("👋 Hi! Tell me about a transaction, like 'Pay 768 yen at Sukiya'.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """First entry point for user messages that aren't commands."""
    if not is_user_authorized(update.effective_user.id):
        return  # Do not respond if the user is not authorized

    # Send a loading message
    loading_message = await update.message.reply_text("⏳ Processing your request...")

    user_text = update.message.text.strip()
    proposal = intent_filter.determine_intent(user_text)

    if not proposal:
        await loading_message.edit_text("❌ I couldn't parse your message. Try again.")
        return

    context.user_data["proposal"] = proposal
    context.user_data["original_input"] = user_text

    # If there's missing info, we handle that. For example, if it's "withdrawal" 
    # and "source_id" is missing, we prompt the user to pick. If "transfer", we might 
    # need both "source_id" and "destination_id".
    # We'll do a quick check:
    if "source_id" in proposal["missing_info"] or "destination_id" in proposal["missing_info"]:
        await loading_message.delete()
        await prompt_for_accounts(update, context, proposal)
        return

    # If no critical missing info, present the confirmation menu
    await loading_message.delete()
    await present_proposal(update, proposal)

async def present_proposal(update: Update, proposal: dict):
    """Show the user a summary of the final transaction and ask for confirmation."""
    msg = (
        "Proposed Transaction"
        "📋 Type:{type}\n"
        "💰 Amount: {amount} {currency_code}\n"
        "📝 Description: {description}\n"
        "🏦 Source: {source_name}(ID: {source_id})\n"
        "📤 Destination: {destination_name} (ID: {destination_id})\n"
        "📂 Category: {category_name}\n"
        "🏷️ Tags: {tags} \n"
        "🧾 Bill: {bill_name} (ID: {bill_id})\n"
        "❓ Missing Info: {missing_info}\n"
        "📅 Date: {date} \n"
    ).format(
        type=proposal['type'],
        amount=proposal['amount'],
        currency_code=proposal['currency_code'],
        description=proposal['description'],
        source_name=proposal['source_name'],
        source_id=proposal['source_id'],
        destination_name=proposal['destination_name'],
        destination_id=proposal['destination_id'],
        bill_name=proposal['bill_name'],
        bill_id=proposal['bill_id'],
        category_name=proposal['category_name'],
        tags=', '.join(proposal['tags']) if proposal['tags'] else 'None',
        missing_info=', '.join(proposal['missing_info']) if proposal['missing_info'] else 'None',
        date=proposal['date']
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ OK", callback_data="ok"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ],
        [InlineKeyboardButton("➕ Add Context", callback_data="add_context")]
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def prompt_for_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE, proposal: dict):
    """
    If user is missing source/destination, offer an account picker.
    We'll do it in a simple step: pick source first, then destination if needed.
    """
    if not is_user_authorized(update.effective_user.id):
        return  # Do not respond if the user is not authorized

    accounts = fetch_accounts()
    if not accounts:
        await update.message.reply_text("No accounts found. Please add some accounts first.")
        return

    # We'll store the user_data that we need to pick. 
    # For instance, if it's a withdrawal, we might only need source. If it's a transfer, we need both.
    needed = []
    if proposal["type"] in ("withdrawal") and "source_id" in proposal["missing_info"]:
        needed.append("source_id")
    if proposal["type"] in ("deposit") and "destination_id" in proposal["missing_info"]:
        needed.append("destination_id")
    elif proposal["type"] == "transfer":
        if "source_id" in proposal["missing_info"]:
            needed.append("source_id")
        if "destination_id" in proposal["missing_info"]:
            needed.append("destination_id")
    

    if not needed:
        # If there's no needed accounts to pick, we can just present the normal menu
        await present_proposal(update, proposal)
        return

    # We'll pick the first needed field. 
    # A more advanced approach might prompt them sequentially for each one.
    field_to_pick = needed[0]
    context.user_data["field_to_pick"] = field_to_pick

    # Build inline keyboard with each account as a button
    buttons = []
    for (acc_id, acc_name) in accounts:
        buttons.append([InlineKeyboardButton(f"{acc_name} (ID {acc_id})",
                      callback_data=f"pick_account_{acc_id}")])

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.effective_message.reply_text(
        f"Please select {field_to_pick} from your available asset accounts:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def account_picker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles user picking an account from the inline keyboard."""
    if not is_user_authorized(update.effective_user.id):
        return  # Do not respond if the user is not authorized

    query = update.callback_query
    await query.answer()

    data = query.data  # e.g. 'pick_account_12'
    if not data.startswith("pick_account_"):
        return

    acc_id_str = data.replace("pick_account_", "")
    try:
        acc_id = int(acc_id_str)
    except ValueError:
        await query.edit_message_text("Invalid account ID selected.")
        return

    # Put the chosen ID into the proposal
    proposal = context.user_data.get("proposal")
    field_to_pick = context.user_data.get("field_to_pick")

    if not proposal or not field_to_pick:
        await query.edit_message_text("No proposal or field to update.")
        return

    proposal[field_to_pick] = acc_id
    # Remove from missing_info if present
    if field_to_pick in proposal["missing_info"]:
        proposal["missing_info"].remove(field_to_pick)

    # Clear the field from user_data
    context.user_data["field_to_pick"] = None

    # If there's still other missing info, we might want to prompt again.
    # For example, if this is a transfer, we might still need 'destination_id'.
    if proposal["type"] == "transfer":
        # Check if the other one is still missing
        if "destination_id" in proposal["missing_info"]:
            # Prompt for destination now
            await prompt_for_accounts(query, context, proposal)
            return

    # If all done picking, show final proposal
    await query.edit_message_text("✅ Account selected.")
    # Show final summary
    await present_proposal_after_pick(query, proposal)

async def present_proposal_after_pick(query, proposal):
    """Re-send the final summary after picking an account from the inline keyboard."""
    msg = (
        f"🚀 Updated transaction:\n"
        f"Type: {proposal['type']}\n"
        f"Amount: {proposal['amount']} {proposal['currency_code']}\n"
        f"Description: {proposal['description']}\n"
        f"Source ID: {proposal['source_id']}\n"
        f"Destination ID: {proposal['destination_id']}\n"
        f"Category: {proposal['category_name']}\n"
        f"Tags: {proposal['tags']}\n"
        f"Bill ID: {proposal['bill_id']}\n"
        f"Missing Info: {proposal['missing_info']}\n"
        f"Date: {proposal['date']}\n"
        "\nNow confirm or regenerate?"
    )
    keyboard = [
        [
            InlineKeyboardButton("OK", callback_data="ok"),
            InlineKeyboardButton("Regenerate", callback_data="regenerate"),
            InlineKeyboardButton("Cancel", callback_data="cancel")
        ],
        [InlineKeyboardButton("Add Context", callback_data="add_context")]
    ]
    await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def post_transaction(proposal: dict):
    """Post the transaction to Firefly's /transactions API using call_firefly_api_curl."""
    endpoint = "/transactions"

    # Build base transaction payload
    transaction = {
        "type": proposal["type"],
        "date": proposal["date"],
        "amount": str(proposal["amount"]),
        "description": proposal["description"],
        "currency_code": proposal["currency_code"],
        "category_name": proposal["category_name"]
    }

    # Add source_id and destination_id only if they exist and are not empty
    if proposal.get("source_id") != "unknown":
        # add and parse to integer
        transaction["source_id"] = int(proposal["source_id"])
    if proposal.get("destination_id") != "unknown":
        transaction["destination_id"] = int(proposal["destination_id"])
    if proposal.get("bill_id") != "unknown":
        transaction["bill_id"] = int(proposal["bill_id"])
    if proposal.get("tags"):
        transaction["tags"] = proposal["tags"]

    payload = {"transactions": [transaction]}

    logging.debug(f"POST Payload: {json.dumps(payload, indent=2)}")
    response = call_firefly_api_curl(endpoint, method="POST", data=payload)
    if response and "errors" not in response:
        logging.info(f"Transaction successfully posted to Firefly. Response: {response}")
        
        # Extract and display the inserted transaction details
        transaction_data = response.get("data", {}).get("attributes", {}).get("transactions", [])
        if transaction_data:
            transaction_details = transaction_data[0]
            success_message = (
                f"✅ Transaction successfully inserted:\n"
                f"Type: {transaction_details['type']}\n"
                f"Amount: {transaction_details['amount']} {transaction_details['currency_code']}\n"
                f"Description: {transaction_details['description']}\n"
                f"Source: {transaction_details['source_name']} (ID: {transaction_details['source_id']})\n"
                f"Destination: {transaction_details['destination_name']} (ID: {transaction_details['destination_id']})\n"
                f"Tags: {', '.join(transaction_details['tags'])}\n"
                f"Category: {transaction_details['category_name']}\n"
                f"Date: {transaction_details['date']}\n"
            )
            return success_message
        return True
    elif response and "errors" in response:
        logging.error(f"Failed to post transaction. Errors: {response['errors']}")
        return response  # Return the error response for further handling
    else:
        logging.error("Failed to post transaction. No valid response received.")
        return False

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle OK, Regenerate, Add Context, Cancel from the main menu."""
    if not is_user_authorized(update.effective_user.id):
        return  # Do not respond if the user is not authorized

    query = update.callback_query
    await query.answer()
    proposal = context.user_data.get("proposal")

    if not proposal:
        await query.edit_message_text("⚠️ No proposal in progress.")
        return

    action = query.data
    if action == "ok":
        result = await post_transaction(proposal)
        if result is True:
            await query.edit_message_text("✅ Transaction confirmed and sent to Firefly!")
        elif isinstance(result, dict) and "errors" in result:
            error_message = "\n".join([f"{key}: {', '.join(value)}" for key, value in result["errors"].items()])
            await query.edit_message_text(f"❌ Failed to send transaction. Errors:\n{error_message}")
        elif isinstance(result, str):
            await query.edit_message_text(result)
        else:
            await query.edit_message_text("❌ Failed to send transaction. Please try again.")
        context.user_data.clear()

    elif action == "regenerate":
        original_input = context.user_data.get("original_input", "")
        new_proposal = intent_filter.determine_intent(original_input)
        if new_proposal:
            context.user_data["proposal"] = new_proposal

            # If the new proposal is missing source/dest, prompt again
            if "source_id" in new_proposal["missing_info"] or "destination_id" in new_proposal["missing_info"]:
                await prompt_for_accounts(update, context, new_proposal)
                return

            await query.edit_message_text("Regenerated proposal.")
            await present_proposal_after_pick(query, new_proposal)
        else:
            await query.edit_message_text("❌ Could not regenerate.")

    elif action == "add_context":
        await query.edit_message_text("Please provide additional context (e.g. 'for dinner' or 'for electricity bill').")
        context.user_data["awaiting_context"] = True

    elif action == "cancel":
        await query.edit_message_text("Operation cancelled.")
        context.user_data.clear()

async def handle_additional_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """If the user wanted to add context, we re-run the LLM with the new input."""
    if not is_user_authorized(update.effective_user.id):
        return  # Do not respond if the user is not authorized

    if not context.user_data.get("awaiting_context"):
        return await handle_message(update, context)

    additional = update.message.text.strip()
    original_input = context.user_data.get("original_input", "")
    new_input = f"{original_input}, {additional}"

    new_proposal = intent_filter.determine_intent(new_input)
    if not new_proposal:
        await update.message.reply_text("❌ Could not parse with the added context.")
        return

    context.user_data["proposal"] = new_proposal
    context.user_data["original_input"] = new_input
    context.user_data.pop("awaiting_context", None)

    if "source_id" in new_proposal["missing_info"] or "destination_id" in new_proposal["missing_info"]:
        await prompt_for_accounts(update, context, new_proposal)
    else:
        await present_proposal(update, new_proposal)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_additional_context))
    app.add_handler(CallbackQueryHandler(button_callback, pattern="^(ok|regenerate|add_context|cancel)$"))
    app.add_handler(CallbackQueryHandler(account_picker_callback, pattern="^pick_account_"))

    print("🚀 Bot is running. Talk to it on Telegram!")
    app.run_polling()

if __name__ == "__main__":
    main()
