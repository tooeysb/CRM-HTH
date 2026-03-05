"""Add composite indexes for dashboard performance.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-03-05
"""

from alembic import op

revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade():
    # Critical: composite index for email queries sorted by date per user
    # Fixes full table scans on dashboard's recent emails and volume queries
    op.create_index(
        "ix_emails_user_id_date",
        "emails",
        ["user_id", "date"],
    )


def downgrade():
    op.drop_index("ix_emails_user_id_date")
