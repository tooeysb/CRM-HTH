#!/usr/bin/env python3
"""Check EmailQueue status for procore-main account."""

import sys

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.models import EmailQueue, GmailAccount

engine = create_engine(settings.database_url)
Session = sessionmaker(bind=engine)
db = Session()

try:
    # Get procore-main account
    account = db.query(GmailAccount).filter_by(account_label="procore-main").first()
    if not account:
        print("ERROR: procore-main account not found")
        sys.exit(1)

    print(f"Account: {account.account_email} ({account.id})")

    # Check EmailQueue status
    total = db.query(func.count(EmailQueue.id)).filter_by(account_id=account.id).scalar()
    unclaimed = (
        db.query(func.count(EmailQueue.id))
        .filter_by(account_id=account.id, claimed_by=None)
        .scalar()
    )
    claimed = (
        db.query(func.count(EmailQueue.id))
        .filter(EmailQueue.account_id == account.id, EmailQueue.claimed_by.isnot(None))
        .scalar()
    )

    print("\nEmailQueue Status:")
    print(f"  Total IDs:     {total:,}")
    print(f"  Unclaimed:     {unclaimed:,}")
    print(f"  Claimed:       {claimed:,}")

    # Get Gmail total (if available)
    if hasattr(account, "gmail_total_emails") and account.gmail_total_emails:
        print(f"\nGmail Total:     {account.gmail_total_emails:,}")
        print(f"DB Email Count:  {209210:,}")
        print(f"Still to fetch:  {account.gmail_total_emails - 209210:,}")
    else:
        print("\nGmail total not set in account model")

finally:
    db.close()
