"""Create linkedin_posts table for tracking contact activity.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-03-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "m3n4o5p6q7r8"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "linkedin_posts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "post_url",
            sa.String(2048),
            nullable=False,
            unique=True,
            comment="LinkedIn post permalink (dedup key)",
        ),
        sa.Column(
            "post_text",
            sa.Text(),
            nullable=True,
            comment="Post content (first 2000 chars)",
        ),
        sa.Column(
            "post_date",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the post was published",
        ),
        sa.Column(
            "post_type",
            sa.String(20),
            nullable=True,
            comment="original, shared, article, comment",
        ),
        sa.Column(
            "engagement_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total likes + comments + reposts",
        ),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="When this post was scraped",
        ),
        sa.Column(
            "is_new",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="True until user marks as seen",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Partial index for fast "new posts" dashboard query
    op.create_index(
        "ix_linkedin_posts_is_new",
        "linkedin_posts",
        ["is_new"],
        postgresql_where=sa.text("is_new = true"),
    )
    op.create_index("ix_linkedin_posts_post_date", "linkedin_posts", ["post_date"])


def downgrade():
    op.drop_index("ix_linkedin_posts_post_date", table_name="linkedin_posts")
    op.drop_index("ix_linkedin_posts_is_new", table_name="linkedin_posts")
    op.drop_table("linkedin_posts")
