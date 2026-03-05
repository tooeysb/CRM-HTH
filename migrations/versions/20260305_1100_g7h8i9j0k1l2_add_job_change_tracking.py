"""Add job change tracking fields to contacts.

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-05
"""

import sqlalchemy as sa
from alembic import op

revision = "g7h8i9j0k1l2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "contacts",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "contacts",
        sa.Column("linkedin_company_raw", sa.String(500), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("job_change_detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("last_linkedin_check_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "previous_company_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_contacts_is_active", "contacts", ["is_active"])
    op.create_index("ix_contacts_last_linkedin_check_at", "contacts", ["last_linkedin_check_at"])


def downgrade():
    op.drop_index("ix_contacts_last_linkedin_check_at")
    op.drop_index("ix_contacts_is_active")
    op.drop_column("contacts", "previous_company_id")
    op.drop_column("contacts", "last_linkedin_check_at")
    op.drop_column("contacts", "job_change_detected_at")
    op.drop_column("contacts", "linkedin_company_raw")
    op.drop_column("contacts", "is_active")
