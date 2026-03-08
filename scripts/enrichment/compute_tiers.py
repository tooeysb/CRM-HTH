#!/usr/bin/env python3
"""
Compute monitoring tiers for contacts based on email signal strength.

Usage:
    python -m scripts.enrichment.compute_tiers              # Assign tiers
    python -m scripts.enrichment.compute_tiers --dry-run    # Preview only
"""

from __future__ import annotations

import argparse

from src.core.database import SyncSessionLocal
from src.core.logging import get_logger
from src.models.user import User
from src.services.enrichment.monitoring_tier import compute_tiers_for_user

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Compute LinkedIn monitoring tiers")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    args = parser.parse_args()

    db = SyncSessionLocal()
    try:
        # Get the primary user
        user = db.query(User).first()
        if not user:
            logger.error("No user found")
            return

        logger.info("Computing monitoring tiers for user %s", user.id)
        counts = compute_tiers_for_user(db, user.id, dry_run=args.dry_run)

        logger.info("Results: %s", counts)
        print(f"Tier A: {counts['A']}")
        print(f"Tier B: {counts['B']}")
        print(f"Tier C: {counts['C']}")
        if counts["skipped_manual"]:
            print(f"Skipped (manual override): {counts['skipped_manual']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
