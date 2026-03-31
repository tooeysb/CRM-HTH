"""Add is_direct to discovered_contacts

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-05 09:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discovered_contacts",
        sa.Column(
            "is_direct",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True if person had direct email interaction (sent to or received from user)",
        ),
    )
    op.create_index(
        "ix_discovered_contacts_is_direct",
        "discovered_contacts",
        ["is_direct"],
    )


def downgrade() -> None:
    op.drop_index("ix_discovered_contacts_is_direct", table_name="discovered_contacts")
    op.drop_column("discovered_contacts", "is_direct")
