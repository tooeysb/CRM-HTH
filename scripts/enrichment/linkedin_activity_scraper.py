#!/usr/bin/env python3
"""
LinkedIn activity scraper — monitors contact posts for engagement opportunities.

Visits each contact's /recent-activity/all/ page, extracts recent posts,
and saves new ones to the CRM for the dashboard and daily digest.

Usage:
    python -m scripts.enrichment.linkedin_activity_scraper              # Full run
    python -m scripts.enrichment.linkedin_activity_scraper --tier A     # Only tier A
    python -m scripts.enrichment.linkedin_activity_scraper --limit 10   # Process N
    python -m scripts.enrichment.linkedin_activity_scraper --dry-run    # Preview
    python -m scripts.enrichment.linkedin_activity_scraper --setup      # Login
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from scripts.enrichment.browser import LinkedInBrowser, LinkedInPostData  # noqa: E402
from scripts.enrichment.crm_client import CRMClient  # noqa: E402
from scripts.enrichment.human_behavior import delay_between_profiles  # noqa: E402
from src.core.config import settings  # noqa: E402
from src.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)

API_BASE = os.environ.get("ENRICHMENT_API_BASE", "https://crm-hth-0f0e9a31256d.herokuapp.com")
API_KEY = os.environ.get("ENRICHMENT_API_KEY", "")


def _post_to_api_dict(post: LinkedInPostData) -> dict:
    """Convert a LinkedInPostData to the API request format."""
    result = {
        "post_url": post.post_url or "",
        "post_type": post.post_type,
        "engagement_count": post.engagement_count,
    }
    if post.post_text:
        result["post_text"] = post.post_text[:2000]
    if post.post_date_raw:
        days_ago = LinkedInBrowser.parse_relative_date(post.post_date_raw)
        if days_ago is not None:
            post_dt = datetime.now(UTC) - timedelta(days=days_ago)
            result["post_date"] = post_dt.isoformat()
    return result


def main():
    parser = argparse.ArgumentParser(description="LinkedIn activity scraper")
    parser.add_argument("--setup", action="store_true", help="Interactive LinkedIn login")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--limit", type=int, default=0, help="Max contacts to process (0=all)")
    parser.add_argument("--tier", choices=["A", "B", "C"], help="Only process this tier")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--proxy", action="store_true", help="Use rotating proxy")
    args = parser.parse_args()

    browser = LinkedInBrowser(headless=args.headless, proxy=args.proxy)

    if args.setup:
        browser.setup_auth()
        return

    logger.info(
        "Activity scraper starting (tier=%s, dry_run=%s, limit=%s, proxy=%s)",
        args.tier or "all",
        args.dry_run,
        args.limit or "unlimited",
        args.proxy,
    )

    api_key = API_KEY or settings.secret_key
    if not api_key:
        logger.error("No API key")
        return

    crm = CRMClient(base_url=API_BASE, api_key=api_key)

    # Fetch contacts due for post check
    contacts = crm.get_needs_post_check(tier=args.tier)
    logger.info("Contacts due for post check: %d", len(contacts))

    if args.limit:
        contacts = contacts[: args.limit]

    if not contacts:
        logger.info("No contacts need post checking — done")
        return

    # Graceful shutdown
    shutdown_requested = False

    def _signal_handler(signum, frame):
        nonlocal shutdown_requested
        logger.info("Shutdown requested — finishing current contact")
        shutdown_requested = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    total_new_posts = 0
    total_duplicates = 0
    contacts_checked = 0

    try:
        browser.start()

        for i, contact in enumerate(contacts):
            if shutdown_requested:
                break

            cid = contact["id"]
            name = contact.get("name", "Unknown")
            linkedin_url = contact["linkedin_url"]
            tier = contact.get("monitoring_tier", "?")

            logger.info(
                "[%d/%d] Checking: %s (tier %s) — %s",
                i + 1,
                len(contacts),
                name,
                tier,
                linkedin_url,
            )

            # Extract recent posts
            posts = browser.extract_recent_activity(linkedin_url, max_posts=5)
            contacts_checked += 1

            if not posts:
                logger.info("No posts found for %s", name)
                # Still update last_post_check_at
                if not args.dry_run:
                    crm.update_contact(cid, last_post_check_at=datetime.now(UTC).isoformat())
                continue

            # Filter posts that have a URL (needed for dedup)
            valid_posts = [p for p in posts if p.post_url]
            if not valid_posts:
                logger.info("Posts found for %s but none had extractable URLs", name)
                if not args.dry_run:
                    crm.update_contact(cid, last_post_check_at=datetime.now(UTC).isoformat())
                continue

            # Save to CRM
            api_posts = [_post_to_api_dict(p) for p in valid_posts]

            if args.dry_run:
                logger.info("DRY RUN: Would save %d posts for %s", len(api_posts), name)
                for p in valid_posts:
                    snippet = (p.post_text or "")[:80]
                    logger.info("  - [%s] %s... (%s)", p.post_type, snippet, p.post_date_raw)
            else:
                result = crm.create_linkedin_posts(cid, api_posts)
                created = result.get("created", 0)
                dupes = result.get("duplicates", 0)
                total_new_posts += created
                total_duplicates += dupes
                logger.info("Saved for %s: %d new, %d duplicates", name, created, dupes)

            # Pace between profiles
            if i < len(contacts) - 1 and not shutdown_requested:
                delay_between_profiles()

    finally:
        browser.stop()
        crm.close()

    logger.info(
        "Activity scraper complete: %d contacts checked, %d new posts, %d duplicates",
        contacts_checked,
        total_new_posts,
        total_duplicates,
    )


if __name__ == "__main__":
    main()
