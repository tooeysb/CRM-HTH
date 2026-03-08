"""Add monitoring tier and title tracking fields to contacts.

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-03-07
"""

import sqlalchemy as sa
from alembic import op

revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade():
    # Monitoring tier fields
    op.add_column(
        "contacts",
        sa.Column("monitoring_tier", sa.String(1), nullable=True, comment="A/B/C monitoring tier"),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "tier_auto_suggested",
            sa.String(1),
            nullable=True,
            comment="Auto-computed tier suggestion from email data",
        ),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "tier_manually_set",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether user overrode auto-suggested tier",
        ),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "last_post_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When LinkedIn posts were last scraped for this contact",
        ),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "last_profile_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When LinkedIn profile was last checked for job/title changes",
        ),
    )

    # Title change tracking
    op.add_column(
        "contacts",
        sa.Column(
            "linkedin_title_raw",
            sa.String(500),
            nullable=True,
            comment="Job title as seen on LinkedIn during last check",
        ),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "title_change_detected_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When a title mismatch was detected on LinkedIn",
        ),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "previous_title",
            sa.String(255),
            nullable=True,
            comment="Job title before most recent change was detected",
        ),
    )

    # Indexes for tier-based scheduling queries
    op.create_index("ix_contacts_monitoring_tier", "contacts", ["monitoring_tier"])
    op.create_index("ix_contacts_last_post_check_at", "contacts", ["last_post_check_at"])
    op.create_index("ix_contacts_last_profile_check_at", "contacts", ["last_profile_check_at"])


def downgrade():
    op.drop_index("ix_contacts_last_profile_check_at", table_name="contacts")
    op.drop_index("ix_contacts_last_post_check_at", table_name="contacts")
    op.drop_index("ix_contacts_monitoring_tier", table_name="contacts")
    op.drop_column("contacts", "previous_title")
    op.drop_column("contacts", "title_change_detected_at")
    op.drop_column("contacts", "linkedin_title_raw")
    op.drop_column("contacts", "last_profile_check_at")
    op.drop_column("contacts", "last_post_check_at")
    op.drop_column("contacts", "tier_manually_set")
    op.drop_column("contacts", "tier_auto_suggested")
    op.drop_column("contacts", "monitoring_tier")
