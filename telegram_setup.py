"""
Telegram first-time authentication helper.

Run this once to authenticate and generate a session string:

    python telegram_setup.py

The session string is printed at the end — copy it into your .env file as:
    TELEGRAM_SESSION=<the string>

After that, telegram_ch.py will use the session string without needing
a phone number or SMS code again.
"""

import sys
import os

try:
    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    print("telethon is not installed. Run: pip install telethon")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(__file__))
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH

if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
    print(
        "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in your .env file.\n"
        "Get them from: https://my.telegram.org → API development tools"
    )
    sys.exit(1)

print("Authenticating with Telegram...")
print("You will receive an SMS or in-app code on your Telegram account.\n")

with TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH) as client:
    client.start()
    session_string = client.session.save()

print("\n" + "=" * 60)
print("Authentication successful!")
print("Copy this session string into your .env file as TELEGRAM_SESSION=")
print("=" * 60)
print(session_string)
print("=" * 60)
print("\nDo NOT share this string — it grants full access to your Telegram account.")
