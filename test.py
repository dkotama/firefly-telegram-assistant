import os
import asyncio
from dotenv import load_dotenv
import telegram
import requests
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Load environment variables from .env file
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FIREFLY_API_TOKEN = os.getenv("FIREFLY_API_TOKEN")
FIREFLY_API_URL = os.getenv("FIREFLY_API_URL")

# Global variable to store chat_id
CHAT_ID = None

# Handle /start command to get chat_id
async def start(update, context):
    global CHAT_ID
    CHAT_ID = update.message.chat_id
    await update.message.reply_text(f"Chat ID detected: {CHAT_ID}. Connection test successful!")
    print(f"Telegram Bot Connected: @{context.bot.username}")
    print(f"Chat ID retrieved: {CHAT_ID}")
    print("Test message sent to Telegram successfully.")

# Handle any message to ensure chat_id is captured
async def handle_message(update, context):
    global CHAT_ID
    if CHAT_ID is None:
        CHAT_ID = update.message.chat_id
        await update.message.reply_text(f"Chat ID detected: {CHAT_ID}. Connection test successful!")
        print(f"Telegram Bot Connected: @{context.bot.username}")
        print(f"Chat ID retrieved: {CHAT_ID}")
        print("Test message sent to Telegram successfully.")

# Test Telegram Bot Connection with automated chat_id retrieval
async def test_telegram_connection():
    try:
        # Set up the bot application
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        print("Telegram Bot is running... Please send a message to the bot (e.g., /start).")
        
        # Start polling for updates
        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        # Wait for a few seconds to allow user interaction
        await asyncio.sleep(10)  # Adjust this duration as needed

        # Stop polling after chat_id is retrieved or timeout
        await application.updater.stop()
        await application.stop()

        if CHAT_ID is None:
            print("No chat ID retrieved. Please message the bot within 10 seconds.")
        else:
            print("Telegram connection test completed.")

    except Exception as e:
        print(f"Telegram Connection Failed: {str(e)}")

# Test Firefly III API Connection
def test_firefly_connection():
    try:
        # Headers matching curl exactly
        headers = {
            "accept": "application/json",  # Lowercase to match curl
            "Authorization": f"Bearer {FIREFLY_API_TOKEN}"
        }
        
        url = f"{FIREFLY_API_URL}/about"
        print(f"Requesting URL: {url}")
        print(f"Token (partial): {FIREFLY_API_TOKEN[:10]}...")
        print(f"Headers: {headers}")
        
        # Make request without following redirects
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        if response.status_code == 200:
            data = response.json()
            print("Firefly III API Connected Successfully!")
            print(f"Firefly III Version: {data['data']['version']}")
        else:
            print(f"Firefly III Connection Failed: {response.status_code}")
            print(f"Response: {response.text[:500]}...")
            
        # Test with curl-like User-Agent if it fails
        if response.status_code != 200:
            print("\nRetrying with curl User-Agent...")
            headers["User-Agent"] = "curl/7.68.0"  # Mimic curl
            response = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
            
            print(f"Status Code: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")
            if response.status_code == 200:
                data = response.json()
                print("Firefly III API Connected Successfully with curl User-Agent!")
                print(f"Firefly III Version: {data['data']['version']}")
            else:
                print(f"Firefly III Connection Failed with curl User-Agent: {response.status_code}")
                print(f"Response: {response.text[:500]}...")

    except requests.exceptions.SSLError as e:
        print(f"SSL Error: {str(e)}")
        print("Retrying with SSL verification disabled...")
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:500]}...")
    except Exception as e:
        print(f"Firefly III Connection Failed: {str(e)}")

# Run both tests
async def run_tests(choice):
    if choice == "1":
        print("1. Testing Telegram Bot Connection:")
        await test_telegram_connection()
    elif choice == "2":
        print("\n2. Testing Firefly III API Connection:")
        test_firefly_connection()
    else:
        print("1. Testing Telegram Bot Connection:")
        await test_telegram_connection()
        print("\n2. Testing Firefly III API Connection:")
        test_firefly_connection()

def main():
    print("Testing connections...\n")
    choice = input("Choose test to run (1=Telegram, 2=Firefly, anything else=both): ")
    asyncio.run(run_tests(choice))

if __name__ == "__main__":
    main()