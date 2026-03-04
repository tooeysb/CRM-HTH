"""Add news_search_override to companies

Revision ID: e29bf653f294
Revises: 007_add_news_intelligence
Create Date: 2026-03-04 10:22:27.514476

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e29bf653f294"
down_revision = "007_add_news_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "news_search_override",
            sa.String(length=255),
            nullable=True,
            comment="Override search term for Google News (e.g. 'DPR Construction' for 'DPR')",
        ),
    )


def downgrade() -> None:
    op.drop_column("companies", "news_search_override")
