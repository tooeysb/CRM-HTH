#!/usr/bin/env python3
"""
Fetch and insert ONLY the 1,692 missing emails.
This is the most efficient approach - we know exactly which IDs to fetch!
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
    # Load missing IDs
    missing_ids_file = "/tmp/missing_email_ids.txt"
    with open(missing_ids_file, "r") as f:
        missing_ids = [line.strip() for line in f if line.strip()]

    print(f"Loading {len(missing_ids):,} missing email IDs...")
    print("=" * 80)
    print()

    engine = create_engine(settings.database_url)

    with Session(engine) as db:
        account = db.query(GmailAccount).filter(
            GmailAccount.account_email == "2e@procore.com"
        ).first()

        if not account:
            print("ERROR: Could not find account")
            return

        user_id = account.user_id

        credentials_dict = json.loads(account.credentials) if isinstance(account.credentials, str) else account.credentials
        gmail_client = GmailClient(credentials=credentials_dict)

        print(f"Fetching {len(missing_ids):,} missing emails...")
        print()

        # Process in batches of 100
        batch_size = 100
        total_inserted = 0
        total_skipped = 0

        for i in range(0, len(missing_ids), batch_size):
            batch = missing_ids[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(missing_ids) + batch_size - 1) // batch_size

            print(f"Batch {batch_num}/{total_batches}: Fetching {len(batch)} emails...")

            # Fetch full message details
            try:
                email_dicts = gmail_client.fetch_message_batch(batch)

                # Create Email objects
                for email_dict in email_dicts:
                    try:
                        # Date is already a datetime object from fetch_message_batch
                        # Create Email object
                        email = Email(
                            user_id=user_id,
                            account_id=account.id,
                            gmail_message_id=email_dict["gmail_message_id"],
                            gmail_thread_id=email_dict.get("gmail_thread_id"),
                            subject=email_dict.get("subject"),
                            sender_email=email_dict["sender_email"],
                            sender_name=email_dict.get("sender_name"),
                            recipient_emails=email_dict["recipient_emails"],
                            date=email_dict["date"],
                            summary=email_dict.get("snippet"),  # snippet -> summary
                            has_attachments=email_dict.get("has_attachments", False),
                            attachment_count=email_dict.get("attachment_count", 0),
                        )

                        # Insert with UPSERT (skip if already exists)
                        db.add(email)
                        db.flush()  # Try to insert
                        total_inserted += 1

                    except Exception as e:
                        # Duplicate or other error - skip
                        db.rollback()
                        total_skipped += 1
                        continue

                # Commit batch
                db.commit()
                print(f"  ✓ Batch {batch_num}: Inserted {len(email_dicts)} emails")

            except Exception as e:
                print(f"  ✗ Batch {batch_num}: Error - {str(e)}")
                db.rollback()
                continue

        print()
        print("=" * 80)
        print("DONE!")
        print("=" * 80)
        print(f"Total emails inserted: {total_inserted:,}")
        print(f"Total skipped (duplicates): {total_skipped:,}")
        print()

        # Verify final count
        final_count = db.query(Email).filter(Email.account_id == account.id).count()
        print(f"Final database count: {final_count:,}")
        print(f"Expected: 85,401 + {total_inserted:,} = {85401 + total_inserted:,}")
        print()

        if final_count >= 87000:
            print("✅ SUCCESS! All missing emails have been fetched!")
        else:
            print(f"⚠️  Still missing {87092 - final_count:,} emails")

if __name__ == "__main__":
    main()
