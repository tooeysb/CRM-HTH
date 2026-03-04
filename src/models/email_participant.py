"""
EmailParticipant junction model linking emails to contacts by role.
"""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.contact import Contact
    from src.models.email import Email


class EmailParticipant(Base, UUIDMixin, TimestampMixin):
    """
    Junction table linking emails to contacts with role information.
    Enables structured queries like "all emails where contact X was a recipient".
    """

    __tablename__ = "email_participants"
    __table_args__ = (
        UniqueConstraint("email_id", "contact_id", "role", name="uq_email_contact_role"),
        Index("ix_email_participants_contact_role", "contact_id", "role"),
    )

    # Foreign Keys
    email_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("emails.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Email this participation record belongs to",
    )

    contact_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Contact who participated in this email",
    )

    # Role
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Participation role: sender, to, cc, bcc",
    )

    # Relationships
    email: Mapped["Email"] = relationship("Email", back_populates="participants")

    contact: Mapped["Contact"] = relationship("Contact", back_populates="email_participants")

    def __repr__(self) -> str:
        return (
            f"<EmailParticipant(id={self.id}, email_id={self.email_id}, "
            f"contact_id={self.contact_id}, role={self.role})>"
        )
