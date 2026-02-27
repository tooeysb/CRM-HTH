"""Email queue model for ID-first fetching strategy."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from src.models.base import Base


class EmailQueue(Base):
    """
    Queue of Gmail message IDs pending full message fetch.

    This table stores just the message IDs after a fast messages.list() call.
    Workers then claim batches of IDs and fetch the full message content.

    Benefits:
    - Faster initial scan (messages.list uses 1 quota unit vs 5 for full fetch)
    - Better parallelization (multiple workers can claim different batches)
    - Easy resume on failure (just fetch unclaimed IDs)
    - Accurate progress tracking (know total count upfront)
    """

    __tablename__ = "email_queue"
    __table_args__ = (
        UniqueConstraint("account_id", "gmail_message_id", name="uq_email_queue_account_message"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("gmail_accounts.id"), nullable=False)
    gmail_message_id = Column(String(255), nullable=False, index=True)

    # Worker coordination
    claimed_by = Column(String(255), nullable=True)  # Worker/task ID that claimed this
    claimed_at = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<EmailQueue {self.gmail_message_id} account={self.account_id}>"
