#!/usr/bin/env python3
"""Directly process the 700 queued personal account emails, bypassing Celery."""
import json
import uuid
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert

from src.core.config import settings
from src.models import Email, EmailQueue, GmailAccount
from src.integrations.gmail.client import GmailClient

# Database setup
engine = create_engine(settings.database_url)
Session = sessionmaker(bind=engine)
db = Session()

# Get personal account
account = db.query(GmailAccount).filter(
    GmailAccount.account_label == 'personal'
).first()

if not account:
    print("❌ Personal account not found")
    exit(1)

# Get all queued IDs for personal account
queued_ids = db.query(EmailQueue.gmail_message_id).filter(
    EmailQueue.account_id == account.id
).all()

message_ids = [row[0] for row in queued_ids]

print(f"📧 Found {len(message_ids)} queued emails for {account.account_email}")

if len(message_ids) == 0:
    print("✅ No emails to process!")
    exit(0)

# Create Gmail client
creds = json.loads(account.credentials)
gmail_client = GmailClient(creds)

# Fetch emails in batches of 100
batch_size = 100
total_processed = 0

for i in range(0, len(message_ids), batch_size):
    batch = message_ids[i:i + batch_size]
    print(f"\n🔄 Processing batch {i//batch_size + 1}/{(len(message_ids) + batch_size - 1)//batch_size} ({len(batch)} emails)...")

    try:
        # Fetch full messages
        email_dicts = gmail_client.fetch_message_batch(batch)
        print(f"  Fetched {len(email_dicts)} full messages")

        # Insert into Email table
        emails_to_insert = []
        for email_dict in email_dicts:
            email_data = {
                "id": uuid.uuid4(),
                "user_id": account.user_id,
                "account_id": account.id,
                "gmail_message_id": email_dict["gmail_message_id"],
                "gmail_thread_id": email_dict.get("gmail_thread_id"),
                "subject": email_dict.get("subject", ""),
                "sender_email": email_dict.get("sender_email", ""),
                "sender_name": email_dict.get("sender_name"),
                "recipient_emails": email_dict.get("recipient_emails", ""),
                "date": email_dict.get("date", datetime.utcnow()),
                "summary": email_dict.get("snippet", "")[:500],
                "has_attachments": email_dict.get("has_attachments", False),
                "attachment_count": email_dict.get("attachment_count", 0),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
            emails_to_insert.append(email_data)

        if emails_to_insert:
            stmt = insert(Email).on_conflict_do_nothing(
                index_elements=["account_id", "gmail_message_id"]
            )
            db.execute(stmt, emails_to_insert)
            db.commit()
            print(f"  ✅ Inserted {len(emails_to_insert)} emails")
            total_processed += len(emails_to_insert)

        # Remove from queue
        db.query(EmailQueue).filter(
            EmailQueue.account_id == account.id,
            EmailQueue.gmail_message_id.in_(batch)
        ).delete(synchronize_session=False)
        db.commit()
        print(f"  🗑️  Removed {len(batch)} from queue")

    except Exception as e:
        print(f"  ❌ Error: {e}")
        continue

print(f"\n✅ DONE! Processed {total_processed} emails for {account.account_email}")
print(f"🗑️  Cleared queue")

db.close()
