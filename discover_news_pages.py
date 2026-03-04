"""
Discover news/press/insights pages for all companies.

Usage:
    python discover_news_pages.py                    # Discover all
    python discover_news_pages.py --limit 10         # Test with 10
    python discover_news_pages.py --dry-run          # Preview only
    python discover_news_pages.py --dry-run --limit 5
"""

import argparse
import sys

from src.core.database import SyncSessionLocal
from src.models.user import User
from src.services.news.discovery import NewsPageDiscoveryService


def main():
    parser = argparse.ArgumentParser(description="Discover company news pages")
    parser.add_argument("--limit", type=int, default=None, help="Max companies to check")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't save")
    args = parser.parse_args()

    db = SyncSessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            print("No user found in database")
            sys.exit(1)

        print(f"User: {user.email}")
        print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
        if args.limit:
            print(f"Limit: {args.limit}")
        print()

        service = NewsPageDiscoveryService(db)
        try:
            stats = service.discover_all(
                user_id=str(user.id),
                limit=args.limit,
                dry_run=args.dry_run,
            )
        finally:
            service.close()

        print(f"\nResults: {stats}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
