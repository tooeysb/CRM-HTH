"""Add linkedin_name to companies for name mismatch tracking.

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-03-05 14:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "linkedin_name",
            sa.String(255),
            nullable=True,
            comment="Company name as shown on LinkedIn (for mismatch review)",
        ),
    )


def downgrade() -> None:
    op.drop_column("companies", "linkedin_name")
