"""
Import customer data from Adidas Master List Excel spreadsheet into CRM models.

Usage:
    python import_customer_data.py "/path/to/Adidas Master List.xlsx"
    python import_customer_data.py "/path/to/Adidas Master List.xlsx" --dry-run
    python import_customer_data.py "/path/to/Adidas Master List.xlsx" --tab "Over 1M Customers"
    python import_customer_data.py --build-participants
    python import_customer_data.py --stats

Phases:
    1. Company Resolution — create Company records from spreadsheet
    2. Contact Import — match/create contacts, tag by source tab
    3. Merge — apply tab priority rules, update RelationshipProfiles
    4. EmailParticipant Build — populate junction table from 1.16M emails (--build-participants)
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core.database import SyncSessionLocal
from src.models.company import Company
from src.models.contact import Contact
from src.models.contact_enrichment import ContactEnrichment
from src.models.email_participant import EmailParticipant
from src.models.user import User

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def show_stats(db):
    """Display current enrichment statistics."""
    company_count = db.query(Company).count()
    contact_count = db.query(Contact).count()
    enriched_count = db.query(Contact).filter(Contact.company_id.isnot(None)).count()
    vip_count = db.query(Contact).filter(Contact.is_vip.is_(True)).count()
    tagged_count = db.query(Contact).filter(Contact.tags != []).count()
    enrichment_count = db.query(ContactEnrichment).count()
    participant_count = db.query(EmailParticipant).count()

    logger.info("=" * 60)
    logger.info("CRM ENRICHMENT STATISTICS")
    logger.info("=" * 60)
    logger.info(f"  Companies:              {company_count:>8,}")
    logger.info(f"  Total contacts:         {contact_count:>8,}")
    logger.info(f"  Enriched (has company): {enriched_count:>8,}")
    logger.info(f"  VIP contacts:           {vip_count:>8,}")
    logger.info(f"  Tagged contacts:        {tagged_count:>8,}")
    logger.info(f"  Enrichment audit rows:  {enrichment_count:>8,}")
    logger.info(f"  Email participants:     {participant_count:>8,}")
    logger.info("=" * 60)

    # Breakdown by tab
    if enrichment_count > 0:
        from sqlalchemy import func

        tab_stats = (
            db.query(
                ContactEnrichment.source_tab,
                ContactEnrichment.match_status,
                func.count().label("cnt"),
            )
            .group_by(ContactEnrichment.source_tab, ContactEnrichment.match_status)
            .order_by(ContactEnrichment.source_tab)
            .all()
        )

        logger.info("\nEnrichment by tab:")
        current_tab = None
        for row in tab_stats:
            if row.source_tab != current_tab:
                current_tab = row.source_tab
                logger.info(f"\n  {current_tab}:")
            logger.info(f"    {row.match_status:<12s}: {row.cnt:>5,}")


def main():
    parser = argparse.ArgumentParser(description="Import customer data from Excel spreadsheet")
    parser.add_argument(
        "filepath",
        nargs="?",
        help="Path to Excel spreadsheet (e.g., Adidas Master List.xlsx)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and show stats without writing to database",
    )
    parser.add_argument(
        "--tab",
        type=str,
        default=None,
        help="Only process a specific tab (e.g., 'Over 1M Customers')",
    )
    parser.add_argument(
        "--build-participants",
        action="store_true",
        help="Run Phase 4: populate EmailParticipant table from existing emails",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show current enrichment statistics",
    )
    args = parser.parse_args()

    db = SyncSessionLocal()
    try:
        # Get the user
        user = db.query(User).first()
        if not user:
            logger.error("No user found in database. Run email sync first.")
            sys.exit(1)

        logger.info(f"Using user: {user.email} (id={user.id})")

        # --stats mode
        if args.stats:
            show_stats(db)
            return

        # --build-participants mode (Phase 4)
        if args.build_participants:
            from src.services.enrichment.email_participant_builder import EmailParticipantBuilder

            logger.info("")
            logger.info("=" * 60)
            logger.info("PHASE 4: EmailParticipant Build")
            logger.info("=" * 60)

            builder = EmailParticipantBuilder(user.id, db)
            count = builder.build_all()
            logger.info(f"\nCreated {count:,} EmailParticipant rows")
            return

        # Phases 1-3 require a filepath
        if not args.filepath:
            parser.error("filepath is required unless using --build-participants or --stats")

        filepath = Path(args.filepath)
        if not filepath.exists():
            logger.error(f"File not found: {filepath}")
            sys.exit(1)

        logger.info(f"Spreadsheet: {filepath}")

        # Parse Excel
        from src.services.enrichment.excel_importer import ExcelImporter

        importer = ExcelImporter(filepath)
        tabs_data = importer.parse_all_tabs()

        # Filter to single tab if requested
        if args.tab:
            if args.tab not in tabs_data:
                logger.error(f"Tab '{args.tab}' not found. Available tabs: {list(tabs_data.keys())}")
                sys.exit(1)
            tabs_data = {args.tab: tabs_data[args.tab]}

        # Print parse summary
        logger.info("\nParsed tabs:")
        total_rows = 0
        for tab_name, rows in tabs_data.items():
            emails_in_tab = sum(1 for r in rows if r.get("email"))
            logger.info(f"  {tab_name:<35s}: {len(rows):>5,} rows ({emails_in_tab:>4,} with email)")
            total_rows += len(rows)
        logger.info(f"  {'TOTAL':<35s}: {total_rows:>5,} rows")

        if args.dry_run:
            # Show match preview against existing contacts
            existing = {
                c.email.lower(): c
                for c in db.query(Contact).filter(Contact.user_id == user.id).all()
            }
            logger.info(f"\nExisting contacts in DB: {len(existing):,}")

            all_emails = set()
            for rows in tabs_data.values():
                for row in rows:
                    email = row.get("email", "")
                    if email:
                        all_emails.add(email.strip().lower())

            matched = all_emails & set(existing.keys())
            unmatched = all_emails - set(existing.keys())
            logger.info(f"Unique emails in spreadsheet: {len(all_emails):,}")
            logger.info(f"  Would match existing:       {len(matched):,}")
            logger.info(f"  Would create new:           {len(unmatched):,}")
            logger.info("\n--dry-run flag set, no database changes made.")
            return

        # Phase 1: Company Resolution
        from src.services.enrichment.company_resolver import CompanyResolver

        logger.info("")
        logger.info("=" * 60)
        logger.info("PHASE 1: Company Resolution")
        logger.info("=" * 60)

        resolver = CompanyResolver(user.id, db)
        company_map = resolver.resolve_companies(tabs_data)
        logger.info(f"Resolved {len(company_map)} companies")

        # Phase 2: Contact Import
        from src.services.enrichment.contact_matcher import ContactMatcher

        logger.info("")
        logger.info("=" * 60)
        logger.info("PHASE 2: Contact Import")
        logger.info("=" * 60)

        matcher = ContactMatcher(user.id, db, source_file=filepath.name)
        import_stats = matcher.match_and_import(tabs_data, company_map)
        logger.info(f"\nImport results: {import_stats}")

        # Phase 3: Merge
        from src.services.enrichment.enrichment_merger import EnrichmentMerger

        logger.info("")
        logger.info("=" * 60)
        logger.info("PHASE 3: Enrichment Merge")
        logger.info("=" * 60)

        merger = EnrichmentMerger(user.id, db)
        merge_stats = merger.merge_all()
        logger.info(f"\nMerge results: {merge_stats}")

        # Summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("IMPORT COMPLETE")
        logger.info("=" * 60)
        show_stats(db)

    finally:
        db.close()


if __name__ == "__main__":
    main()
