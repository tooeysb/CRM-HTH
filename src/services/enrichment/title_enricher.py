"""
Batch title enrichment for newly promoted contacts.
Uses Haiku email signature extraction (fast, batched) then LinkedIn search (slower, rate-limited).
"""

import time
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload

from src.core.logging import get_logger
from src.models.contact import Contact

logger = get_logger(__name__)

# Rate limit for LinkedIn/DuckDuckGo searches to avoid getting blocked
LINKEDIN_SEARCH_DELAY_SECONDS = 2.0
# Max contacts to process via LinkedIn search per run
LINKEDIN_BATCH_LIMIT = 100
# Max contacts to process via Haiku per batch call
HAIKU_BATCH_SIZE = 20


class BatchTitleEnricher:
    """Batch title enrichment for contacts without titles."""

    def __init__(self, user_id: UUID, db: Session):
        self.user_id = user_id
        self.db = db

    def enrich_titles(
        self,
        contact_ids: list[UUID] | None = None,
        linkedin_limit: int = LINKEDIN_BATCH_LIMIT,
    ) -> dict:
        """
        Enrich titles for contacts missing them.

        Strategy:
        1. First pass: batch Haiku signature extraction (fast, handles many at once)
        2. Second pass: LinkedIn search for remaining (rate-limited, slower)

        Returns stats dict.
        """
        from src.api.routers.crm import _search_linkedin_title  # noqa: F811

        # 1. Load contacts needing titles
        query = (
            self.db.query(Contact)
            .options(selectinload(Contact.company))
            .filter(
                Contact.user_id == self.user_id,
                Contact.title.is_(None),
            )
        )
        if contact_ids:
            query = query.filter(Contact.id.in_(contact_ids))

        contacts = query.all()
        logger.info("Found %d contacts needing title enrichment", len(contacts))

        if not contacts:
            return {"total": 0, "haiku_enriched": 0, "linkedin_enriched": 0, "failed": 0}

        # 2. Group by company for efficient batching
        company_groups: dict[UUID | None, list] = {}
        for c in contacts:
            company_groups.setdefault(c.company_id, []).append(c)

        haiku_enriched = 0
        linkedin_enriched = 0
        linkedin_remaining = linkedin_limit

        for _company_id, company_contacts in company_groups.items():
            company = company_contacts[0].company
            company_name = company.name if company else ""
            company_aliases = company.aliases if company else None
            company_domain = company.domain if company else None

            # Phase 1: Haiku signature batch (fast, handles many at once)
            still_need_title = []
            haiku_count = self._enrich_via_haiku(company_contacts, company_name)
            haiku_enriched += haiku_count

            for c in company_contacts:
                if not c.title:
                    still_need_title.append(c)

            # Phase 2: LinkedIn search (rate-limited) for remaining
            for contact in still_need_title:
                if linkedin_remaining <= 0 or not contact.name:
                    continue

                title = _search_linkedin_title(
                    contact.name, company_name, company_aliases, company_domain
                )
                if title:
                    contact.title = title
                    linkedin_enriched += 1
                    logger.info("LinkedIn title for %s: %s", contact.name, title)

                linkedin_remaining -= 1
                time.sleep(LINKEDIN_SEARCH_DELAY_SECONDS)

        self.db.commit()
        failed = len(contacts) - haiku_enriched - linkedin_enriched

        stats = {
            "total": len(contacts),
            "haiku_enriched": haiku_enriched,
            "linkedin_enriched": linkedin_enriched,
            "failed": failed,
        }
        logger.info("Title enrichment complete: %s", stats)
        return stats

    def _enrich_via_haiku(self, contacts: list[Contact], company_name: str) -> int:
        """Batch-enrich titles via Haiku signature extraction for a set of contacts."""
        from src.api.routers.crm import _enrich_with_haiku

        sender_emails = [c.email.lower() for c in contacts if c.name]
        if not sender_emails:
            return 0

        # Fetch most recent email body for each contact (as sender)
        sig_rows = self.db.execute(
            text(
                """
                SELECT DISTINCT ON (LOWER(sender_email))
                       sender_email, body
                FROM emails
                WHERE user_id = :uid
                  AND LOWER(sender_email) = ANY(:emails)
                  AND body IS NOT NULL
                  AND LENGTH(body) > 50
                ORDER BY LOWER(sender_email), date DESC
                """
            ),
            {"uid": str(self.user_id), "emails": sender_emails},
        ).fetchall()

        contact_lookup = {c.email.lower(): c for c in contacts}
        signatures: dict[str, tuple[str, str]] = {}
        for row in sig_rows:
            email_key = row.sender_email.lower().strip()
            c = contact_lookup.get(email_key)
            if c and c.name:
                signatures[email_key] = (c.name, row.body)

        if not signatures:
            return 0

        # Process in sub-batches
        enriched_count = 0
        sig_items = list(signatures.items())
        for i in range(0, len(sig_items), HAIKU_BATCH_SIZE):
            batch = dict(sig_items[i : i + HAIKU_BATCH_SIZE])
            try:
                enriched = _enrich_with_haiku(batch, company_name)
                for email_key, info in enriched.items():
                    title = info.get("title")
                    if title and email_key in contact_lookup:
                        contact_lookup[email_key].title = title
                        enriched_count += 1
            except Exception:
                logger.warning(
                    "Haiku enrichment failed for batch at %s", company_name, exc_info=True
                )

        return enriched_count
