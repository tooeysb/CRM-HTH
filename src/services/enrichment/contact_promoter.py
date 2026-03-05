"""
Contact promoter: auto-promotes discovered contacts with direct email interaction
to full CRM contacts. Runs after domain discovery as a chained task.
"""

import uuid as uuid_mod
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.models.contact import Contact
from src.models.discovered_contact import DiscoveredContact

logger = get_logger(__name__)


class ContactPromoter:
    """Promotes discovered contacts with direct email interaction to CRM contacts."""

    def __init__(self, user_id: UUID, db: Session):
        self.user_id = user_id
        self.db = db

    def promote_direct_contacts(self) -> dict:
        """
        Find all discovered contacts with is_direct=True that are not yet
        CRM contacts, and create Contact records for them.

        Returns dict with stats and list of promoted contact IDs + emails.
        """
        # 1. Load existing contact emails to avoid duplicates
        existing_emails = self._load_existing_contact_emails()
        logger.info("Found %d existing CRM contact emails", len(existing_emails))

        # 2. Query all direct discovered contacts
        stmt = (
            select(DiscoveredContact)
            .where(
                DiscoveredContact.user_id == self.user_id,
                DiscoveredContact.is_direct.is_(True),
            )
            .order_by(DiscoveredContact.email_count.desc())
        )
        direct_contacts = self.db.execute(stmt).scalars().all()
        logger.info("Found %d direct discovered contacts", len(direct_contacts))

        # 3. Filter out existing contacts
        to_promote = []
        skipped = 0
        for dc in direct_contacts:
            if dc.email.lower().strip() in existing_emails:
                skipped += 1
                continue
            to_promote.append(dc)

        logger.info(
            "%d to promote, %d already exist as CRM contacts",
            len(to_promote),
            skipped,
        )

        if not to_promote:
            return {
                "promoted": 0,
                "skipped_existing": skipped,
                "total_direct": len(direct_contacts),
                "promoted_contacts": [],
            }

        # 4. Bulk insert Contact records
        chunk_size = 500
        total_promoted = 0
        promoted_contacts = []  # (contact_id, email) pairs

        for i in range(0, len(to_promote), chunk_size):
            chunk = to_promote[i : i + chunk_size]
            new_ids = [uuid_mod.uuid4() for _ in chunk]
            values = [
                {
                    "id": new_id,
                    "user_id": self.user_id,
                    "company_id": dc.company_id,
                    "email": dc.email.lower().strip(),
                    "name": dc.name,
                    "email_count": dc.email_count,
                    "last_contact_at": dc.last_email_at,
                    "account_sources": [],
                    "is_vip": False,
                    "tags": [],
                }
                for new_id, dc in zip(new_ids, chunk, strict=True)
            ]
            stmt = pg_insert(Contact.__table__).values(values)
            stmt = stmt.on_conflict_do_nothing(constraint="uq_user_contact_email")
            result = self.db.execute(stmt)
            total_promoted += result.rowcount

            # Track promoted contacts for downstream linking/enrichment
            for new_id, dc in zip(new_ids, chunk, strict=True):
                promoted_contacts.append({"id": new_id, "email": dc.email.lower().strip()})

        self.db.commit()
        logger.info("Promoted %d discovered contacts to CRM contacts", total_promoted)

        return {
            "promoted": total_promoted,
            "skipped_existing": skipped,
            "total_direct": len(direct_contacts),
            "promoted_contacts": promoted_contacts,
        }

    def _load_existing_contact_emails(self) -> set[str]:
        """Load all existing CRM contact emails (lowercase)."""
        stmt = select(Contact.email).where(Contact.user_id == self.user_id)
        rows = self.db.execute(stmt).all()
        return {email.lower() for (email,) in rows if email}
