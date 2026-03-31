"""Add CRM data model: companies, email_participants, contact_enrichments, and contact CRM fields

Revision ID: 005_add_crm_models
Revises: 004_add_voice_profiles
Create Date: 2026-03-02 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "005_add_crm_models"
down_revision = "004_add_voice_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create companies table
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("aliases", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("company_type", sa.String(100), nullable=True),
        sa.Column("billing_state", sa.String(100), nullable=True),
        sa.Column("arr", sa.Numeric(15, 2), nullable=True),
        sa.Column("revenue_segment", sa.String(50), nullable=True),
        sa.Column("account_tier", sa.String(50), nullable=True),
        sa.Column("salesforce_id", sa.String(100), nullable=True),
        sa.Column("renewal_date", sa.Date, nullable=True),
        sa.Column("account_owner", sa.String(255), nullable=True),
        sa.Column("csm", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("source_data", postgresql.JSON, nullable=True),
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
            nullable=False,
        ),
    )

    op.create_index("ix_companies_user_id", "companies", ["user_id"])
    op.create_index("ix_companies_name", "companies", ["name"])
    op.create_index("ix_companies_domain", "companies", ["domain"])
    op.create_unique_constraint("uq_user_company_name", "companies", ["user_id", "name"])

    # 2. Add CRM columns to contacts
    op.add_column(
        "contacts",
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("contacts", sa.Column("title", sa.String(255), nullable=True))
    op.add_column("contacts", sa.Column("personal_email", sa.String(255), nullable=True))
    op.add_column("contacts", sa.Column("contact_type", sa.String(50), nullable=True))
    op.add_column(
        "contacts", sa.Column("is_vip", sa.Boolean, server_default="false", nullable=False)
    )
    op.add_column(
        "contacts",
        sa.Column("tags", postgresql.ARRAY(sa.String), server_default="{}", nullable=False),
    )
    op.add_column("contacts", sa.Column("salesforce_id", sa.String(100), nullable=True))
    op.add_column("contacts", sa.Column("address", sa.Text, nullable=True))
    op.add_column("contacts", sa.Column("source_data", postgresql.JSON, nullable=True))

    op.create_index("ix_contacts_company_id", "contacts", ["company_id"])

    # 3. Create email_participants junction table
    op.create_table(
        "email_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
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
            nullable=False,
        ),
    )

    op.create_index("ix_email_participants_email_id", "email_participants", ["email_id"])
    op.create_index("ix_email_participants_contact_id", "email_participants", ["contact_id"])
    op.create_index(
        "ix_email_participants_contact_role",
        "email_participants",
        ["contact_id", "role"],
    )
    op.create_unique_constraint(
        "uq_email_contact_role",
        "email_participants",
        ["email_id", "contact_id", "role"],
    )

    # 4. Create contact_enrichments audit table
    op.create_table(
        "contact_enrichments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("match_email", sa.String(255), nullable=False),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_file", sa.String(255), nullable=False),
        sa.Column("source_tab", sa.String(100), nullable=False),
        sa.Column("source_row", sa.Integer, nullable=True),
        sa.Column("raw_data", postgresql.JSON, nullable=True),
        sa.Column("match_status", sa.String(20), nullable=False),
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
            nullable=False,
        ),
    )

    op.create_index("ix_contact_enrichments_match_email", "contact_enrichments", ["match_email"])
    op.create_index("ix_contact_enrichments_source_tab", "contact_enrichments", ["source_tab"])
    op.create_unique_constraint(
        "uq_enrichment_source",
        "contact_enrichments",
        ["user_id", "source_tab", "match_email"],
    )

    # 5. Add customer_data to relationship_profiles
    op.add_column(
        "relationship_profiles",
        sa.Column("customer_data", postgresql.JSON, nullable=True),
    )


def downgrade() -> None:
    # 5. Remove customer_data from relationship_profiles
    op.drop_column("relationship_profiles", "customer_data")

    # 4. Drop contact_enrichments
    op.drop_table("contact_enrichments")

    # 3. Drop email_participants
    op.drop_table("email_participants")

    # 2. Remove CRM columns from contacts
    op.drop_index("ix_contacts_company_id", table_name="contacts")
    op.drop_column("contacts", "source_data")
    op.drop_column("contacts", "address")
    op.drop_column("contacts", "salesforce_id")
    op.drop_column("contacts", "tags")
    op.drop_column("contacts", "is_vip")
    op.drop_column("contacts", "contact_type")
    op.drop_column("contacts", "personal_email")
    op.drop_column("contacts", "title")
    op.drop_column("contacts", "company_id")

    # 1. Drop companies
    op.drop_table("companies")
