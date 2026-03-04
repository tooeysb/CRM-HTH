#!/usr/bin/env python3
"""
Test Gmail API pagination to see if we're actually fetching all available emails.
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

        print(f"Testing pagination for account: {account.account_email}")
        print("=" * 80)
        print()

        # Test with no query (default - should get everything)
        print("Testing pagination with NO query filter (should get all emails):")
        print("-" * 80)

        page_num = 0
        total_fetched = 0
        next_page_token = None

        while True:
            page_num += 1

            response = gmail_client.gmail_service.users().messages().list(
                userId='me',
                maxResults=500,  # Maximum allowed per request
                pageToken=next_page_token if next_page_token else None
            ).execute()

            messages = response.get('messages', [])
            result_size_estimate = response.get('resultSizeEstimate', 0)
            next_page_token = response.get('nextPageToken')

            total_fetched += len(messages)

            print(f"Page {page_num}: fetched {len(messages)} messages, "
                  f"resultSizeEstimate={result_size_estimate:,}, "
                  f"total_fetched={total_fetched:,}, "
                  f"has_next={'YES' if next_page_token else 'NO'}")

            # Stop after 5 pages or when no more pages
            if not next_page_token or page_num >= 5:
                break

        print()
        print("=" * 80)
        print(f"SUMMARY:")
        print(f"  Pages fetched: {page_num}")
        print(f"  Total messages retrieved: {total_fetched:,}")
        print(f"  Expected (from profile): 87,086")
        print(f"  Still has more pages: {'YES' if next_page_token else 'NO'}")
        print(f"  Missing: {87086 - total_fetched:,} ({((87086 - total_fetched) / 87086 * 100):.2f}%)")
        print()

        if total_fetched < 1000:
            print("⚠️  WARNING: Only fetched a tiny fraction of expected emails!")
            print("    This suggests Gmail API is NOT returning all emails.")
            print()
            print("    Possible causes:")
            print("    - API quota limits")
            print("    - Permission/scope issues")
            print("    - Account-specific restrictions")
            print("    - Gmail API filtering out emails based on some criteria")

if __name__ == "__main__":
    main()
