"""
Simple test script to verify hth-corp email syncing works.
Fetches just 10 emails to test the complete flow.
"""

import json
import uuid
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.integrations.gmail.client import GmailClient
from src.models import Email, GmailAccount

# Database setup
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine)


def test_sync():
    """Test syncing 10 emails from hth-corp account."""
    db = SessionLocal()

    try:
        # Get hth-corp account
        account = (
            db.query(GmailAccount)
            .filter(GmailAccount.account_email == "tooey@hth-corp.com")
            .first()
        )

        if not account:
            print("❌ Account not found")
            return

        print(f"✅ Found account: {account.account_email}")
        print(f"   Account ID: {account.id}")
        print(f"   User ID: {account.user_id}")

        # Get credentials
        creds = json.loads(account.credentials)
        credentials_dict = {
            "access_token": creds.get("token"),
            "refresh_token": creds.get("refresh_token"),
            "token_uri": creds.get("token_uri"),
            "client_id": creds.get("client_id"),
            "client_secret": creds.get("client_secret"),
            "scopes": creds.get("scopes", []),
        }

        # Create Gmail client
        gmail_client = GmailClient(credentials_dict)
        print("✅ Gmail client created")

        # Fetch just 10 message IDs
        print("\n📥 Fetching 10 message IDs...")
        message_ids, _ = gmail_client.fetch_emails_chunked(batch_size=10, query="in:anywhere")
        print(f"✅ Fetched {len(message_ids)} message IDs")

        # Close DB before fetching (test the fix)
        print("\n🔒 Closing DB session before Gmail fetch...")
        db.close()

        # Fetch full messages
        print("📥 Fetching full message details...")
        email_dicts = gmail_client.fetch_message_batch(message_ids)
        print(f"✅ Fetched {len(email_dicts)} full messages")

        # Reopen DB for insertion
        print("\n🔓 Reopening DB session for insertion...")
        db = SessionLocal()

        # Create Email objects
        print("📝 Creating Email objects...")
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

        print(f"✅ Created {len(emails_to_insert)} Email objects")

        # Insert with upsert
        print("\n💾 Inserting into database...")
        stmt = insert(Email).on_conflict_do_nothing(
            index_elements=["account_id", "gmail_message_id"]
        )
        result = db.execute(stmt, emails_to_insert)
        db.commit()
        print("✅ Inserted successfully")

        # Verify count
        from sqlalchemy import func

        count = db.query(func.count(Email.id)).filter(Email.account_id == account.id).scalar()
        print(f"\n📊 Total emails in database for hth-corp: {count}")
        print("\n🎉 TEST PASSED!")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    test_sync()
