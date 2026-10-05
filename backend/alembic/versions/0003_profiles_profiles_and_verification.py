"""profiles_and_verification"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_profiles"
down_revision = "0002_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("business_name", sa.String(length=150), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("website", sa.String(2048), nullable=False),
        sa.Column("logo_url", sa.String(2048), nullable=False),
        sa.Column("cover_image_url", sa.String(2048), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("contact_email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("review_note", sa.String(length=1000), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','UNDER_REVIEW','VERIFIED','REJECTED','SUSPENDED')",
            name="merchant_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id"),
    )
    op.create_index(op.f("ix_merchants_status"), "merchants", ["status"], unique=False)
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("area", sa.String(length=100), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("location_preference", sa.String(length=10), nullable=False),
        sa.CheckConstraint("location_preference IN ('MANUAL','GPS')", name="profile_location"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_events_merchant_id"), "audit_events", ["merchant_id"], unique=False
    )
    op.create_table(
        "staff_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("store_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_staff_invitations_merchant_id"), "staff_invitations", ["merchant_id"], unique=False
    )
    op.create_table(
        "stores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "merchant_id", name="store_merchant_identity"),
    )
    op.create_index(op.f("ix_stores_merchant_id"), "stores", ["merchant_id"], unique=False)
    op.create_table(
        "staff_assignments",
        sa.Column("staff_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["store_id", "merchant_id"], ["stores.id", "stores.merchant_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("staff_id", "store_id"),
    )
    op.create_index(
        op.f("ix_staff_assignments_merchant_id"), "staff_assignments", ["merchant_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_staff_assignments_merchant_id"), table_name="staff_assignments")
    op.drop_table("staff_assignments")
    op.drop_index(op.f("ix_stores_merchant_id"), table_name="stores")
    op.drop_table("stores")
    op.drop_index(op.f("ix_staff_invitations_merchant_id"), table_name="staff_invitations")
    op.drop_table("staff_invitations")
    op.drop_index(op.f("ix_audit_events_merchant_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("profiles")
    op.drop_index(op.f("ix_merchants_status"), table_name="merchants")
    op.drop_table("merchants")
