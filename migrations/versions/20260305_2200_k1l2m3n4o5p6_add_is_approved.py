"""Add is_approved to contacts and companies.

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-03-05 22:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column(
            "is_approved",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Manually approved by user as verified/complete",
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "is_approved",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Manually approved by user as verified/complete",
        ),
    )


def downgrade() -> None:
    op.drop_column("companies", "is_approved")
    op.drop_column("contacts", "is_approved")
