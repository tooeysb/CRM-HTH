"""Add news intelligence: company_news_items, draft_suggestions, and company news columns

Revision ID: 007_add_news_intelligence
Revises: 006_body_null_index
Create Date: 2026-03-05 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "007_add_news_intelligence"
down_revision = "006_body_null_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add news columns to companies
    op.add_column("companies", sa.Column("news_page_url", sa.String(2048), nullable=True))
    op.add_column(
        "companies",
        sa.Column("news_page_discovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column(
            "news_scrape_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # 2. Create company_news_items table
    op.create_table(
        "company_news_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="company_website"),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_html_hash", sa.String(64), nullable=True),
        sa.Column("analysis", postgresql.JSON, nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("ix_company_news_user_id", "company_news_items", ["user_id"])
    op.create_index("ix_company_news_company_id", "company_news_items", ["company_id"])
    op.create_index("ix_company_news_status", "company_news_items", ["status"])
    op.create_index("ix_company_news_published_at", "company_news_items", ["published_at"])
    op.create_unique_constraint(
        "uq_company_news_source", "company_news_items", ["company_id", "source_url"]
    )

    # 3. Create draft_suggestions table
    op.create_table(
        "draft_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "news_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_news_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("context_used", sa.Text, nullable=False),
        sa.Column("tone", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("ix_draft_suggestions_user_id", "draft_suggestions", ["user_id"])
    op.create_index("ix_draft_suggestions_news_item_id", "draft_suggestions", ["news_item_id"])
    op.create_index("ix_draft_suggestions_contact_id", "draft_suggestions", ["contact_id"])
    op.create_index("ix_draft_suggestions_status", "draft_suggestions", ["status"])
    op.create_unique_constraint(
        "uq_draft_news_contact", "draft_suggestions", ["news_item_id", "contact_id"]
    )


def downgrade() -> None:
    op.drop_table("draft_suggestions")
    op.drop_table("company_news_items")
    op.drop_column("companies", "news_scrape_enabled")
    op.drop_column("companies", "news_page_discovered_at")
    op.drop_column("companies", "news_page_url")
