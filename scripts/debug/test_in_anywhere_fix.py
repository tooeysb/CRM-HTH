#!/usr/bin/env python3
"""
Test if adding 'in:anywhere' to our date queries will catch missing emails.
"""

import json
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, func
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

        # Get DB date range
        oldest = db.query(func.min(Email.date)).filter(Email.account_id == account.id).scalar()
        newest = db.query(func.max(Email.date)).filter(Email.account_id == account.id).scalar()

        print("Current Database Date Range:")
        print(f"  Oldest: {oldest}")
        print(f"  Newest: {newest}")
        print()

        print("=" * 80)
        print("TESTING QUERY COMPARISONS")
        print("=" * 80)
        print()

        # Test queries WITH and WITHOUT in:anywhere
        test_cases = [
            {
                "name": "Forward sync WITHOUT in:anywhere",
                "query": f"after:{newest.strftime('%Y/%m/%d')}",
            },
            {
                "name": "Forward sync WITH in:anywhere",
                "query": f"in:anywhere after:{newest.strftime('%Y/%m/%d')}",
            },
            {
                "name": "Backward sync WITHOUT in:anywhere",
                "query": f"before:{oldest.strftime('%Y/%m/%d')}",
            },
            {
                "name": "Backward sync WITH in:anywhere",
                "query": f"in:anywhere before:{oldest.strftime('%Y/%m/%d')}",
            },
        ]

        for test in test_cases:
            print(f"{test['name']}:")
            print(f"  Query: {test['query']}")

            response = gmail_client.gmail_service.users().messages().list(
                userId='me',
                maxResults=10,
                q=test['query']
            ).execute()

            result_count = response.get('resultSizeEstimate', 0)
            messages = response.get('messages', [])

            print(f"  resultSizeEstimate: {result_count:,}")
            print(f"  Actual messages returned: {len(messages)}")

            # Check if any are missing from DB
            if messages:
                missing_count = 0
                for msg in messages[:10]:  # Check first 10
                    exists = db.query(Email).filter(
                        Email.gmail_message_id == msg['id'],
                        Email.account_id == account.id
                    ).first()
                    if not exists:
                        missing_count += 1

                print(f"  Messages NOT in DB (out of {len(messages)}): {missing_count}")

            print()

        print("=" * 80)
        print("VERIFICATION: Check specific missing email")
        print("=" * 80)
        print()

        # The missing email we identified
        missing_id = "1995cef9b1283836"
        missing_date = "2025-09-18"

        # Would it be caught by our current queries?
        current_forward = f"after:{newest.strftime('%Y/%m/%d')}"
        current_backward = f"before:{oldest.strftime('%Y/%m/%d')}"

        # Would it be caught by in:anywhere queries?
        fixed_forward = f"in:anywhere after:{newest.strftime('%Y/%m/%d')}"
        fixed_backward = f"in:anywhere before:{oldest.strftime('%Y/%m/%d')}"

        print(f"Missing email: {missing_id} (date: {missing_date})")
        print(f"Labels: CATEGORY_PROMOTIONS only")
        print()

        # Test if current queries would find it
        print("Testing CURRENT queries (without in:anywhere):")

        for query_name, query in [("Forward", current_forward), ("Backward", current_backward)]:
            response = gmail_client.gmail_service.users().messages().list(
                userId='me',
                maxResults=500,
                q=query
            ).execute()

            messages = response.get('messages', [])
            found = any(msg['id'] == missing_id for msg in messages)

            print(f"  {query_name} query: {query}")
            print(f"    Found missing email? {'✓ YES' if found else '✗ NO'}")

        print()
        print("Testing FIXED queries (with in:anywhere):")

        for query_name, query in [("Forward", fixed_forward), ("Backward", fixed_backward)]:
            response = gmail_client.gmail_service.users().messages().list(
                userId='me',
                maxResults=500,
                q=query
            ).execute()

            messages = response.get('messages', [])
            found = any(msg['id'] == missing_id for msg in messages)

            print(f"  {query_name} query: {query}")
            print(f"    Found missing email? {'✓ YES' if found else '✗ NO'}")

        print()
        print("=" * 80)
        print("CONCLUSION")
        print("=" * 80)
        print()
        print("If the missing email is found with 'in:anywhere' but NOT without it,")
        print("then our fix is confirmed: add 'in:anywhere' to all date queries.")

if __name__ == "__main__":
    main()
