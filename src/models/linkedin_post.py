"""
LinkedIn post model — tracks posts scraped from contact activity feeds.

Used by the LinkedIn monitoring system to surface new posts for engagement
and detect activity patterns across CRM contacts.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.contact import Contact


class LinkedInPost(Base, UUIDMixin, TimestampMixin):
    """
    A LinkedIn post scraped from a contact's recent activity feed.
    Deduplication is handled via unique constraint on post_url.
    """

    __tablename__ = "linkedin_posts"

    contact_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Contact who authored or shared this post",
    )

    post_url: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
        unique=True,
        comment="LinkedIn post permalink (dedup key)",
    )

    post_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Post content (first 2000 chars)"
    )

    post_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When the post was published"
    )

    post_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="original, shared, article, comment"
    )

    engagement_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment="Total likes + comments + reposts",
    )

    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        comment="When this post was scraped",
    )

    is_new: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        comment="True until user marks as seen in CRM dashboard",
    )

    # Relationships
    contact: Mapped["Contact"] = relationship("Contact", back_populates="linkedin_posts")

    def __repr__(self) -> str:
        return f"<LinkedInPost(id={self.id}, contact_id={self.contact_id}, post_type={self.post_type})>"
