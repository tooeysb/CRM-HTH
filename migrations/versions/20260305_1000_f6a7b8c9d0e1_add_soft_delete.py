"""Add soft delete (deleted_at) to companies and contacts

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-05 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_companies_deleted_at", "companies", ["deleted_at"])

    op.add_column(
        "contacts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_contacts_deleted_at", "contacts", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_contacts_deleted_at", table_name="contacts")
    op.drop_column("contacts", "deleted_at")
    op.drop_index("ix_companies_deleted_at", table_name="companies")
    op.drop_column("companies", "deleted_at")
