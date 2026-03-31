"""Add voice_profiles table

Revision ID: 004_add_voice_profiles
Revises: 003_add_email_body
Create Date: 2026-03-01 03:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "004_add_voice_profiles"
down_revision = "003_add_email_body"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_name", sa.String(100), nullable=False, server_default="default"),
        sa.Column("profile_data", postgresql.JSON, nullable=True),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
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

    op.create_index("ix_voice_profiles_user_id", "voice_profiles", ["user_id"])
    op.create_unique_constraint(
        "uq_user_voice_profile", "voice_profiles", ["user_id", "profile_name"]
    )


def downgrade() -> None:
    op.drop_table("voice_profiles")
