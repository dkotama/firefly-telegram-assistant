# Firefly Telegram Assistant

This is a proof-of-concept application that uses the Open AI API to help input Firefly expenses in under 10 seconds.

## Overview

The Firefly Telegram Assistant syncs your Firefly data to a local database and suggests new expenses via Telegram based on your spending patterns. This project is currently in **alpha** stage.

## Technologies Used

- **Telegram API**: For bot communication
- **SQLite**: Local database storage
- **Open AI API**: For intelligent expense suggestions
- **ALL-miniLM-L6-V2**: For similarity detection on blob data in SQLite

## Features

- Syncs Firefly data to a local SQLite database
- Suggests new expenses based on your spending history via Telegram

## Future Updates

1. Code refactoring for better maintainability
2. Add auto-sync functionality
3. Dockerize the application for easier deployment

## How to Run the App

1. **Configure Environment Variables**  
   - Edit the `.env` file and fill in all required tokens (Telegram bot token, Open AI API key, etc.).

2. **Sync Firefly Data**  
   - Run `python firefly_sync.py` to synchronize your Firefly data with the local SQLite database.

3. **Start the Bot**  
   - Run `python main.py` to start the Telegram bot.

4. **Interact with the Bot**  
   - Open Telegram and start talking to your bot!

## Notes

- This is an alpha version, so expect bugs and incomplete features.
- Ensure all dependencies are installed before running the app (e.g., via `requirements.txt` if provided).