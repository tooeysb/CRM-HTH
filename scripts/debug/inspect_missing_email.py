#!/usr/bin/env python3
"""
Inspect a missing email to understand why our date queries didn't fetch it.
"""

import json
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

from src.core.config import settings
from src.integrations.gmail.client import GmailClient
from src.models.account import GmailAccount
from src.models.email import Email


def main():
    # Missing email ID from previous test
    missing_id = "1995cef9b1283836"

    engine = create_engine(settings.database_url)

    with Session(engine) as db:
        account = (
            db.query(GmailAccount).filter(GmailAccount.account_email == "2e@procore.com").first()
        )

        if not account:
            print("ERROR: Could not find account")
            return

        # Parse credentials
        credentials_dict = (
            json.loads(account.credentials)
            if isinstance(account.credentials, str)
            else account.credentials
        )

        gmail_client = GmailClient(credentials=credentials_dict)

        print(f"Inspecting missing email: {missing_id}")
        print("=" * 80)
        print()

        # Fetch full message details
        message = (
            gmail_client.gmail_service.users()
            .messages()
            .get(
                userId="me",
                id=missing_id,
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            .execute()
        )

        # Extract headers
        headers = {h["name"]: h["value"] for h in message.get("payload", {}).get("headers", [])}

        print("Email Details:")
        print("-" * 80)
        print(f"Gmail Message ID: {missing_id}")
        print(f"Thread ID:        {message.get('threadId')}")
        print(f"From:             {headers.get('From', 'N/A')}")
        print(f"To:               {headers.get('To', 'N/A')}")
        print(f"Subject:          {headers.get('Subject', 'N/A')}")
        print(f"Date (header):    {headers.get('Date', 'N/A')}")
        print()

        # Parse date
        date_str = headers.get("Date")
        if date_str:
            try:
                email_date = parsedate_to_datetime(date_str)
                print(f"Parsed Date:      {email_date}")
                print(f"Date (ISO):       {email_date.isoformat()}")
                print()
            except Exception as e:
                email_date = None
                print(f"ERROR parsing date: {e}")
                print()

        # Get database date range
        oldest = db.query(func.min(Email.date)).filter(Email.account_id == account.id).scalar()

        newest = db.query(func.max(Email.date)).filter(Email.account_id == account.id).scalar()

        print("Database Date Range:")
        print("-" * 80)
        print(f"Oldest email in DB: {oldest}")
        print(f"Newest email in DB: {newest}")
        print()

        if email_date:
            print("Analysis:")
            print("-" * 80)

            if email_date < oldest:
                print("❌ This email is OLDER than our oldest DB email!")
                print(f"   Email date:    {email_date}")
                print(f"   Oldest in DB:  {oldest}")
                print(f"   Gap:           {(oldest - email_date).days} days")
                print()
                print("   This email would be fetched by a `before:` query.")
                print(f"   Expected query: before:{oldest.strftime('%Y/%m/%d')}")
                print()
                print("   WHY IT WAS MISSED:")
                print("   Our backward sync queries `before:oldest_date`, but this email")
                print("   might not have been returned due to:")
                print("   - Label filtering (not in INBOX)")
                print("   - Being in SPAM/TRASH")
                print("   - Pagination cutoff")

            elif email_date > newest:
                print("❌ This email is NEWER than our newest DB email!")
                print(f"   Email date:    {email_date}")
                print(f"   Newest in DB:  {newest}")
                print(f"   Gap:           {(email_date - newest).days} days")
                print()
                print("   This email would be fetched by an `after:` query.")
                print(f"   Expected query: after:{newest.strftime('%Y/%m/%d')}")
                print()
                print("   WHY IT WAS MISSED:")
                print("   Our forward sync queries `after:newest_date`, but this email")
                print("   might not have been returned due to:")
                print("   - Label filtering (not in INBOX)")
                print("   - Being in SPAM/TRASH")
                print("   - Exact date boundary (after: vs on the date)")

            else:
                print("⚠️  This email is WITHIN our DB date range!")
                print(f"   Email date:    {email_date}")
                print(f"   DB range:      {oldest} to {newest}")
                print()
                print("   This is a GAP in our data - an email within the date range that")
                print("   we somehow missed during previous scans.")
                print()
                print("   Possible reasons:")
                print("   - Was in SPAM/TRASH and skipped")
                print("   - Added to Gmail after initial backfill")
                print("   - Delivery was delayed (sent earlier, received later)")
                print("   - Was restored from trash")

        # Check labels
        labels = message.get("labelIds", [])
        print()
        print("Labels:")
        print("-" * 80)
        for label in labels:
            print(f"  - {label}")

        if "SPAM" in labels:
            print()
            print("🚨 This email is in SPAM!")
            print("   Our queries might be filtering out SPAM by default.")

        if "TRASH" in labels:
            print()
            print("🚨 This email is in TRASH!")
            print("   Our queries might be filtering out TRASH by default.")

        if "INBOX" not in labels and "SENT" not in labels:
            print()
            print("⚠️  This email is NOT in INBOX or SENT!")
            print("   It might require `in:anywhere` or `in:all` to fetch.")


if __name__ == "__main__":
    main()
