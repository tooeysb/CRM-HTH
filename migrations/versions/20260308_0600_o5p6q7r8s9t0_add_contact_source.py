"""Add contact_source field to contacts.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-03-08
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "o5p6q7r8s9t0"
down_revision = "n4o5p6q7r8s9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "contacts",
        sa.Column(
            "contact_source",
            sa.String(20),
            nullable=True,
            server_default="email",
            comment="How this contact was discovered: email, website, manual",
        ),
    )
    # Backfill all existing contacts as email-discovered
    op.execute("UPDATE contacts SET contact_source = 'email' WHERE contact_source IS NULL")


def downgrade():
    op.drop_column("contacts", "contact_source")
