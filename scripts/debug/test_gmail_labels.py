#!/usr/bin/env python3
"""
Test Gmail API to understand why 1,686 emails are missing.
Queries different labels and checks actual message counts.
"""

import json
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.core.config import settings
from src.integrations.gmail.client import GmailClient
from src.models.account import GmailAccount

def main():
    # Connect to database
    engine = create_engine(settings.database_url)

    with Session(engine) as db:
        # Get procore-private account
        account = db.query(GmailAccount).filter(
            GmailAccount.account_email == "2e@procore.com"
        ).first()

        if not account:
            print("ERROR: Could not find 2e@procore.com account")
            return

        print(f"Testing account: {account.account_email}")
        print(f"Account label: {account.account_label}")
        print()

        # Create Gmail client
        if not account.credentials:
            print("ERROR: Account has no credentials")
            return

        # Parse credentials JSON string to dict
        credentials_dict = json.loads(account.credentials) if isinstance(account.credentials, str) else account.credentials

        gmail_client = GmailClient(
            credentials=credentials_dict
        )

        # 1. Get profile to see actual messagesTotal
        print("=" * 60)
        print("1. GMAIL PROFILE (actual total)")
        print("=" * 60)
        profile = gmail_client.gmail_service.users().getProfile(userId='me').execute()
        messages_total = profile.get('messagesTotal', 0)
        print(f"messagesTotal: {messages_total:,}")
        print()

        # 2. Test different label queries
        test_queries = [
            ("No query (default)", ""),
            ("All mail", "in:anywhere"),
            ("Inbox only", "in:inbox"),
            ("Sent only", "in:sent"),
            ("Drafts", "in:drafts"),
            ("Spam", "in:spam"),
            ("Trash", "in:trash"),
            ("NOT in inbox", "-in:inbox"),
            ("SENT label", "label:SENT"),
            ("TRASH label", "label:TRASH"),
            ("SPAM label", "label:SPAM"),
            ("DRAFT label", "label:DRAFT"),
        ]

        print("=" * 60)
        print("2. QUERY TESTS (resultSizeEstimate)")
        print("=" * 60)

        for description, query in test_queries:
            try:
                response = gmail_client.gmail_service.users().messages().list(
                    userId='me',
                    maxResults=1,
                    q=query if query else None
                ).execute()

                result_size = response.get('resultSizeEstimate', 0)
                print(f"{description:20s} | query: {query:20s} | count: {result_size:,}")
            except Exception as e:
                print(f"{description:20s} | query: {query:20s} | ERROR: {str(e)}")

        print()

        # 3. Check what labels exist
        print("=" * 60)
        print("3. AVAILABLE LABELS")
        print("=" * 60)
        labels_response = gmail_client.gmail_service.users().labels().list(userId='me').execute()
        labels = labels_response.get('labels', [])

        # Sort by type and name
        system_labels = [l for l in labels if l['type'] == 'system']
        user_labels = [l for l in labels if l['type'] == 'user']

        print("\nSystem Labels:")
        for label in sorted(system_labels, key=lambda x: x['name']):
            print(f"  - {label['name']}")

        print(f"\nUser Labels ({len(user_labels)} total):")
        for label in sorted(user_labels, key=lambda x: x['name'])[:20]:  # Show first 20
            print(f"  - {label['name']}")
        if len(user_labels) > 20:
            print(f"  ... and {len(user_labels) - 20} more")

        print()

        # 4. Get actual database count and date range
        print("=" * 60)
        print("4. DATABASE STATE")
        print("=" * 60)
        from src.models.email import Email
        from sqlalchemy import func

        db_count = db.query(func.count(Email.id)).filter(
            Email.account_id == account.id
        ).scalar()

        oldest = db.query(func.min(Email.date)).filter(
            Email.account_id == account.id
        ).scalar()

        newest = db.query(func.max(Email.date)).filter(
            Email.account_id == account.id
        ).scalar()

        print(f"Emails in DB: {db_count:,}")
        print(f"Oldest email: {oldest}")
        print(f"Newest email: {newest}")
        print()

        # 5. Calculate gap
        print("=" * 60)
        print("5. ANALYSIS")
        print("=" * 60)
        print(f"Gmail messagesTotal: {messages_total:,}")
        print(f"Database count:      {db_count:,}")
        print(f"Missing:             {messages_total - db_count:,} emails ({((messages_total - db_count) / messages_total * 100):.2f}%)")
        print()

        # 6. Sample some message IDs from different queries
        print("=" * 60)
        print("6. SAMPLE MESSAGE IDs (first 5 from each query)")
        print("=" * 60)

        sample_queries = [
            ("Default", ""),
            ("in:anywhere", "in:anywhere"),
            ("-in:inbox", "-in:inbox"),
        ]

        for description, query in sample_queries:
            try:
                response = gmail_client.gmail_service.users().messages().list(
                    userId='me',
                    maxResults=5,
                    q=query if query else None
                ).execute()

                messages = response.get('messages', [])
                print(f"\n{description} (query: '{query}'):")
                for msg in messages:
                    msg_id = msg['id']
                    # Check if in DB
                    exists = db.query(Email).filter(
                        Email.gmail_message_id == msg_id,
                        Email.account_id == account.id
                    ).first()
                    status = "✓ in DB" if exists else "✗ NOT in DB"
                    print(f"  {msg_id} - {status}")

            except Exception as e:
                print(f"\n{description}: ERROR - {str(e)}")

if __name__ == "__main__":
    main()
