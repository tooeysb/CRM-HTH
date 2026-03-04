#!/usr/bin/env python3
"""
Directly fetch ONLY the missing email IDs by comparing Gmail with our database.
Much smarter than querying with different filters!
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

        credentials_dict = json.loads(account.credentials) if isinstance(account.credentials, str) else account.credentials
        gmail_client = GmailClient(credentials=credentials_dict)

        print(f"Fetching ALL message IDs from Gmail for: {account.account_email}")
        print("=" * 80)
        print()

        # Step 1: Fetch ALL message IDs from Gmail using in:anywhere
        print("Step 1: Fetching ALL Gmail message IDs (this may take a minute)...")
        gmail_ids = set()
        next_page_token = None
        page_count = 0

        while True:
            page_count += 1
            response = gmail_client.gmail_service.users().messages().list(
                userId='me',
                maxResults=500,
                q='in:anywhere',  # Get EVERYTHING
                pageToken=next_page_token if next_page_token else None
            ).execute()

            messages = response.get('messages', [])
            for msg in messages:
                gmail_ids.add(msg['id'])

            next_page_token = response.get('nextPageToken')

            if page_count % 10 == 0:
                print(f"  Fetched {len(gmail_ids):,} IDs so far ({page_count} pages)...")

            if not next_page_token:
                break

        print(f"✓ Total Gmail message IDs: {len(gmail_ids):,}")
        print()

        # Step 2: Get ALL message IDs from database
        print("Step 2: Fetching database message IDs...")
        db_result = db.query(Email.gmail_message_id).filter(
            Email.account_id == account.id
        ).all()

        db_ids = {row[0] for row in db_result}
        print(f"✓ Total database message IDs: {len(db_ids):,}")
        print()

        # Step 3: Find missing IDs
        missing_ids = gmail_ids - db_ids
        print("=" * 80)
        print("RESULTS:")
        print("=" * 80)
        print(f"Gmail total:     {len(gmail_ids):,}")
        print(f"Database total:  {len(db_ids):,}")
        print(f"Missing IDs:     {len(missing_ids):,}")
        print()

        if missing_ids:
            # Save missing IDs to file for processing
            output_file = "/tmp/missing_email_ids.txt"
            with open(output_file, "w") as f:
                for msg_id in sorted(missing_ids):
                    f.write(f"{msg_id}\n")

            print(f"✓ Saved {len(missing_ids):,} missing email IDs to {output_file}")
            print()
            print("Sample missing IDs (first 20):")
            for i, msg_id in enumerate(sorted(missing_ids)[:20], 1):
                print(f"  {i:2d}. {msg_id}")
            print()

            # Check if our known missing email is in the list
            test_id = "1995cef9b1283836"
            if test_id in missing_ids:
                print(f"✓ Known missing email {test_id} is in the missing list")
            else:
                print(f"✗ Known missing email {test_id} is NOT in the missing list")
            print()

            print("Next step: Fetch full details for these missing IDs only")
            print("This is much more efficient than scanning with queries!")

        else:
            print("⚠️  No missing IDs found!")
            print("This suggests the gap might be in how Gmail reports totals vs queryable emails.")

if __name__ == "__main__":
    main()
