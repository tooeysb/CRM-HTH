"""Add relationship_profiles table

Revision ID: 002_relationship_profiles
Revises: 001_initial
Create Date: 2026-03-01 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "002_relationship_profiles"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "relationship_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("relationship_type", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column(
            "account_sources",
            postgresql.ARRAY(sa.String),
            nullable=False,
            server_default="{}",
        ),
        # Discovery metadata
        sa.Column("total_email_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("received_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_exchange_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_exchange_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thread_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_response_time_hours", sa.Float, nullable=True),
        # Claude-generated profile
        sa.Column("profile_data", postgresql.JSON, nullable=True),
        sa.Column("profiled_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # Indexes
    op.create_index("ix_relationship_profiles_user_id", "relationship_profiles", ["user_id"])
    op.create_index(
        "ix_relationship_profiles_contact_email",
        "relationship_profiles",
        ["contact_email"],
    )
    op.create_index(
        "ix_relationship_profiles_relationship_type",
        "relationship_profiles",
        ["relationship_type"],
    )

    # Unique constraint: one profile per user+contact pair
    op.create_unique_constraint(
        "uq_user_relationship", "relationship_profiles", ["user_id", "contact_email"]
    )


def downgrade() -> None:
    op.drop_table("relationship_profiles")
