"""Add leadership discovery fields to companies.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-03-05
"""

import sqlalchemy as sa
from alembic import op

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "companies",
        sa.Column("leadership_page_url", sa.String(2048), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("leadership_scraped_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("companies", "leadership_scraped_at")
    op.drop_column("companies", "leadership_page_url")
