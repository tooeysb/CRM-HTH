#!/usr/bin/env python3
"""
Find emails that exist in Gmail but NOT in our database.
"""

import json
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.core.config import settings
from src.models.account import GmailAccount
from src.models.email import Email
from src.integrations.gmail.client import GmailClient

def main():
    engine = create_engine(settings.database_url)

    with Session(engine) as db:
        account = db.query(GmailAccount).filter(
            GmailAccount.account_email == "2e@procore.com"
        ).first()

        if not account:
            print("ERROR: Could not find account")
            return

        # Parse credentials
        credentials_dict = json.loads(account.credentials) if isinstance(account.credentials, str) else account.credentials

        gmail_client = GmailClient(credentials=credentials_dict)

        print(f"Finding missing emails for: {account.account_email}")
        print("=" * 80)
        print()

        # Fetch emails from Gmail (no filter - all emails)
        print("Fetching emails from Gmail (10 pages = 5,000 emails)...")
        gmail_ids = set()
        next_page_token = None

        for page in range(10):  # Fetch 10 pages = 5,000 emails
            response = gmail_client.gmail_service.users().messages().list(
                userId='me',
                maxResults=500,
                pageToken=next_page_token if next_page_token else None
            ).execute()

            messages = response.get('messages', [])
            for msg in messages:
                gmail_ids.add(msg['id'])

            next_page_token = response.get('nextPageToken')

            print(f"  Page {page + 1}/10: {len(messages)} messages (total: {len(gmail_ids)})")

            if not next_page_token:
                print("  No more pages available")
                break

        print()
        print(f"Total Gmail IDs fetched: {len(gmail_ids):,}")
        print()

        # Get all message IDs from database for this account
        print("Fetching message IDs from database...")
        db_result = db.query(Email.gmail_message_id).filter(
            Email.account_id == account.id
        ).all()

        db_ids = {row[0] for row in db_result}
        print(f"Total DB IDs: {len(db_ids):,}")
        print()

        # Find missing IDs
        missing_ids = gmail_ids - db_ids
        already_in_db = gmail_ids & db_ids

        print("=" * 80)
        print("RESULTS:")
        print("=" * 80)
        print(f"Emails checked from Gmail: {len(gmail_ids):,}")
        print(f"Already in database:       {len(already_in_db):,}")
        print(f"Missing from database:     {len(missing_ids):,}")
        print()

        if missing_ids:
            print("❌ FOUND MISSING EMAILS!")
            print()
            print(f"Sample missing Gmail message IDs (first 10):")
            for i, msg_id in enumerate(list(missing_ids)[:10], 1):
                print(f"  {i}. {msg_id}")
            print()
            print("These emails exist in Gmail but are NOT in our database.")
            print("This explains the 1,686 email gap!")
            print()
            print("Next steps:")
            print("  1. Fetch full message details for one of these IDs")
            print("  2. Check the date to understand why our date queries missed them")
            print("  3. Update sync logic to catch these emails")

        else:
            print("✅ All fetched emails are already in the database.")
            print()
            print("This suggests the missing 1,686 emails are further back in the pagination.")
            print("They might be:")
            print("  - Very old emails (before our oldest date)")
            print("  - Emails in SPAM/TRASH that were permanently deleted")
            print("  - Emails that were deleted from Gmail after the profile count was taken")

if __name__ == "__main__":
    main()
