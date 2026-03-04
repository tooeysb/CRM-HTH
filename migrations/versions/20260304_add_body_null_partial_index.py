"""Add partial index on emails.body IS NULL for backfill queries.

Revision ID: 006_body_null_index
Revises: 005_add_crm_models
Create Date: 2026-03-04 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "006_body_null_index"
down_revision = "005_add_crm_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Partial index covering the backfill worker's claim query:
    #   SELECT ... FROM emails WHERE account_id = ? AND body IS NULL
    #   LIMIT 500 FOR UPDATE SKIP LOCKED
    # Only indexes rows where body IS NULL, so it shrinks as backfill progresses.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_emails_body_null "
        "ON emails (account_id) WHERE body IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_emails_body_null")
