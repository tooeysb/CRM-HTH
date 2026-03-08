"""
Auto-tiering service for LinkedIn contact monitoring.

Computes a monitoring tier (A/B/C) for each contact based on email signal strength:
- Email count (log-scaled, diminishing returns)
- Recency of last contact
- Whether communication was direct (to/from) vs CC'd

Tier A (~5%): Key relationships, check 2x/week
Tier B (~25%): Active contacts, check weekly
Tier C (rest): Monitor monthly
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.models.contact import Contact

logger = get_logger(__name__)


def compute_contact_score(
    email_count: int,
    last_contact_at: datetime | None,
    is_direct: bool = False,
) -> float:
    """Compute a monitoring priority score for a single contact.

    Scoring:
    - email_count: log2(count) * 10 (diminishing returns on volume)
    - recency: max(0, 100 - days_since_last_email) (linear decay over 100 days)
    - is_direct bonus: +50 (direct correspondents matter more)
    """
    score = 0.0

    # Email volume (log-scaled)
    if email_count > 0:
        score += math.log2(email_count) * 10

    # Recency
    if last_contact_at:
        now = datetime.now(UTC)
        if last_contact_at.tzinfo is None:
            last_contact_at = last_contact_at.replace(tzinfo=UTC)
        days_ago = (now - last_contact_at).days
        score += max(0, 100 - days_ago)

    # Direct communication bonus
    if is_direct:
        score += 50

    return score


def compute_tiers_for_user(db: Session, user_id, dry_run: bool = False) -> dict[str, int]:
    """Compute and assign monitoring tiers for all eligible contacts.

    Args:
        db: Database session
        user_id: User UUID
        dry_run: If True, compute but don't update

    Returns:
        Dict with tier counts: {"A": n, "B": n, "C": n, "skipped_manual": n}
    """
    contacts = (
        db.query(Contact)
        .filter(
            Contact.user_id == user_id,
            Contact.deleted_at.is_(None),
            Contact.is_active.is_(True),
            Contact.linkedin_url.isnot(None),
        )
        .all()
    )

    if not contacts:
        logger.info("No eligible contacts found for tiering")
        return {"A": 0, "B": 0, "C": 0, "skipped_manual": 0}

    # Score all contacts
    scored = []
    for c in contacts:
        score = compute_contact_score(
            email_count=c.email_count or 0,
            last_contact_at=c.last_contact_at,
            is_direct=c.is_vip,  # Use VIP as proxy for "direct" until we have better signal
        )
        scored.append((c, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Assign tiers by percentile
    total = len(scored)
    tier_a_cutoff = max(1, int(total * 0.05))  # Top 5%
    tier_b_cutoff = max(tier_a_cutoff + 1, int(total * 0.25))  # Top 25%

    counts = {"A": 0, "B": 0, "C": 0, "skipped_manual": 0}

    for i, (contact, _score) in enumerate(scored):
        if i < tier_a_cutoff:
            suggested = "A"
        elif i < tier_b_cutoff:
            suggested = "B"
        else:
            suggested = "C"

        contact.tier_auto_suggested = suggested

        if contact.tier_manually_set:
            counts["skipped_manual"] += 1
        else:
            contact.monitoring_tier = suggested

        counts[suggested] += 1

    if not dry_run:
        db.commit()
        logger.info(
            "Tiers assigned: A=%d, B=%d, C=%d (skipped %d manual overrides)",
            counts["A"],
            counts["B"],
            counts["C"],
            counts["skipped_manual"],
        )
    else:
        db.rollback()
        logger.info("Dry run — tiers computed but not saved")

    return counts
