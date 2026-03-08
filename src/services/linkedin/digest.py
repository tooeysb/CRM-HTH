"""
LinkedIn monitoring daily digest — assembles and renders activity summary.

Gathers new posts, job changes, and title changes from the last 24 hours
and sends a formatted HTML email digest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, selectinload

from src.core.logging import get_logger
from src.models.contact import Contact
from src.models.linkedin_post import LinkedInPost

logger = get_logger(__name__)


@dataclass
class PostSummary:
    contact_name: str
    company_name: str | None
    post_text: str | None
    post_url: str
    post_date: datetime | None
    post_type: str | None
    engagement_count: int
    linkedin_url: str | None


@dataclass
class JobChangeSummary:
    contact_name: str
    old_company: str | None
    new_company_raw: str | None
    linkedin_url: str | None
    detected_at: datetime | None


@dataclass
class TitleChangeSummary:
    contact_name: str
    company_name: str | None
    old_title: str | None
    new_title_raw: str | None
    linkedin_url: str | None
    detected_at: datetime | None


@dataclass
class LinkedInDigestData:
    date: datetime
    new_posts: list[PostSummary] = field(default_factory=list)
    job_changes: list[JobChangeSummary] = field(default_factory=list)
    title_changes: list[TitleChangeSummary] = field(default_factory=list)
    tier_counts: dict[str, int] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        return bool(self.new_posts or self.job_changes or self.title_changes)


def build_daily_digest(db: Session, user_id) -> LinkedInDigestData:
    """Assemble digest data from the last 24 hours."""
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)

    data = LinkedInDigestData(date=now)

    # New posts (is_new=True, scraped in last 24h)
    posts = (
        db.query(LinkedInPost)
        .join(Contact)
        .options(selectinload(LinkedInPost.contact).selectinload(Contact.company))
        .filter(
            Contact.user_id == user_id,
            LinkedInPost.is_new.is_(True),
            LinkedInPost.scraped_at >= since,
        )
        .order_by(LinkedInPost.post_date.desc().nullslast())
        .limit(50)
        .all()
    )

    for p in posts:
        data.new_posts.append(
            PostSummary(
                contact_name=p.contact.name or p.contact.email,
                company_name=p.contact.company.name if p.contact.company else None,
                post_text=p.post_text,
                post_url=p.post_url,
                post_date=p.post_date,
                post_type=p.post_type,
                engagement_count=p.engagement_count,
                linkedin_url=p.contact.linkedin_url,
            )
        )

    # Job changes in last 24h
    job_changes = (
        db.query(Contact)
        .options(selectinload(Contact.company))
        .filter(
            Contact.user_id == user_id,
            Contact.deleted_at.is_(None),
            Contact.job_change_detected_at >= since,
        )
        .order_by(Contact.job_change_detected_at.desc())
        .limit(50)
        .all()
    )

    for c in job_changes:
        data.job_changes.append(
            JobChangeSummary(
                contact_name=c.name or c.email,
                old_company=c.company.name if c.company else None,
                new_company_raw=c.linkedin_company_raw,
                linkedin_url=c.linkedin_url,
                detected_at=c.job_change_detected_at,
            )
        )

    # Title changes in last 24h
    title_changes = (
        db.query(Contact)
        .options(selectinload(Contact.company))
        .filter(
            Contact.user_id == user_id,
            Contact.deleted_at.is_(None),
            Contact.title_change_detected_at >= since,
        )
        .order_by(Contact.title_change_detected_at.desc())
        .limit(50)
        .all()
    )

    for c in title_changes:
        data.title_changes.append(
            TitleChangeSummary(
                contact_name=c.name or c.email,
                company_name=c.company.name if c.company else None,
                old_title=c.previous_title,
                new_title_raw=c.linkedin_title_raw,
                linkedin_url=c.linkedin_url,
                detected_at=c.title_change_detected_at,
            )
        )

    logger.info(
        "Digest built: %d posts, %d job changes, %d title changes",
        len(data.new_posts),
        len(data.job_changes),
        len(data.title_changes),
    )
    return data


def render_digest_html(data: LinkedInDigestData) -> tuple[str, str]:
    """Render digest data to (subject, html_body)."""
    parts = []
    if data.new_posts:
        parts.append(f"{len(data.new_posts)} new posts")
    if data.job_changes:
        parts.append(f"{len(data.job_changes)} job changes")
    if data.title_changes:
        parts.append(f"{len(data.title_changes)} title changes")

    subject = (
        f"LinkedIn Digest: {', '.join(parts)}" if parts else "LinkedIn Digest: No new activity"
    )

    # Build HTML
    html_parts = [
        "<html><body style='font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 600px; margin: 0 auto; color: #333;'>",
        "<h2 style='color: #0077b5; border-bottom: 2px solid #0077b5; padding-bottom: 8px;'>LinkedIn Activity Digest</h2>",
        f"<p style='color: #666; font-size: 14px;'>{data.date.strftime('%B %d, %Y')}</p>",
    ]

    # New Posts section
    if data.new_posts:
        html_parts.append(
            f"<h3 style='color: #333; margin-top: 24px;'>New Posts ({len(data.new_posts)})</h3>"
        )
        for p in data.new_posts:
            snippet = (p.post_text or "")[:150]
            if len(p.post_text or "") > 150:
                snippet += "..."
            company_tag = f" at {p.company_name}" if p.company_name else ""
            html_parts.append(
                f"<div style='border-left: 3px solid #0077b5; padding: 8px 12px; margin: 12px 0; background: #f8f9fa;'>"
                f"<strong>{p.contact_name}</strong>{company_tag}"
                f"<br><span style='color: #666; font-size: 13px;'>{snippet}</span>"
                f"<br><a href='{p.post_url}' style='color: #0077b5; font-size: 13px;'>View on LinkedIn</a>"
                f" &middot; <span style='color: #999; font-size: 12px;'>{p.engagement_count} engagements</span>"
                f"</div>"
            )

    # Job Changes section
    if data.job_changes:
        html_parts.append(
            f"<h3 style='color: #333; margin-top: 24px;'>Job Changes ({len(data.job_changes)})</h3>"
        )
        for jc in data.job_changes:
            html_parts.append(
                f"<div style='border-left: 3px solid #e74c3c; padding: 8px 12px; margin: 12px 0; background: #fef9f9;'>"
                f"<strong>{jc.contact_name}</strong>"
                f"<br><span style='color: #666; font-size: 13px;'>{jc.old_company or '?'} &rarr; {jc.new_company_raw or '?'}</span>"
                f"<br><a href='{jc.linkedin_url}' style='color: #0077b5; font-size: 13px;'>View Profile</a>"
                f"</div>"
            )

    # Title Changes section
    if data.title_changes:
        html_parts.append(
            f"<h3 style='color: #333; margin-top: 24px;'>Title Changes ({len(data.title_changes)})</h3>"
        )
        for tc in data.title_changes:
            company_tag = f" at {tc.company_name}" if tc.company_name else ""
            html_parts.append(
                f"<div style='border-left: 3px solid #f39c12; padding: 8px 12px; margin: 12px 0; background: #fefcf5;'>"
                f"<strong>{tc.contact_name}</strong>{company_tag}"
                f"<br><span style='color: #666; font-size: 13px;'>{tc.old_title or '?'} &rarr; {tc.new_title_raw or '?'}</span>"
                f"<br><a href='{tc.linkedin_url}' style='color: #0077b5; font-size: 13px;'>View Profile</a>"
                f"</div>"
            )

    if not data.has_content:
        html_parts.append(
            "<p style='color: #999; font-style: italic; margin-top: 24px;'>No new LinkedIn activity in the last 24 hours.</p>"
        )

    html_parts.append(
        "<hr style='border: none; border-top: 1px solid #ddd; margin-top: 32px;'>"
        "<p style='color: #999; font-size: 12px;'>View full details in your "
        "<a href='https://crm-hth-0f0e9a31256d.herokuapp.com/crm' style='color: #0077b5;'>CRM Dashboard</a></p>"
        "</body></html>"
    )

    return subject, "\n".join(html_parts)
