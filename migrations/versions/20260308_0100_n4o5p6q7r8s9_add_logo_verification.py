"""Add logo verification fields to companies.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-03-08
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "companies",
        sa.Column(
            "logo_verified",
            sa.Boolean(),
            nullable=True,
            comment="Whether website and LinkedIn logos matched",
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "logo_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When logo verification was last run",
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "logo_hash_website",
            sa.String(64),
            nullable=True,
            comment="Perceptual hash of company website logo",
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "logo_hash_linkedin",
            sa.String(64),
            nullable=True,
            comment="Perceptual hash of LinkedIn company logo",
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "logo_hash_distance",
            sa.Integer(),
            nullable=True,
            comment="Hamming distance between website and LinkedIn logo hashes",
        ),
    )


def downgrade():
    op.drop_column("companies", "logo_hash_distance")
    op.drop_column("companies", "logo_hash_linkedin")
    op.drop_column("companies", "logo_hash_website")
    op.drop_column("companies", "logo_verified_at")
    op.drop_column("companies", "logo_verified")
