"""categories_offers"""

import sqlalchemy as sa

from alembic import op

revision = "0005_offers"
down_revision = "0004_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_category_name", "categories", [sa.literal_column("lower(name)")], unique=True
    )
    op.create_table(
        "offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("image_url", sa.String(length=2048), nullable=False),
        sa.Column("discount_type", sa.String(length=30), nullable=False),
        sa.Column("discount_value", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("minimum_purchase", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("maximum_discount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("customer_type", sa.String(length=30), nullable=False),
        sa.Column("terms_conditions", sa.String(length=4000), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("moderation_note", sa.String(length=1000), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("admin_hold", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency = 'INR'", name="offer_currency"),
        sa.CheckConstraint(
            "customer_type IN ('ALL','NEW_CUSTOMERS','EXISTING_CUSTOMERS')",
            name="offer_customer_type",
        ),
        sa.CheckConstraint(
            "discount_type != 'PERCENTAGE' OR (discount_value > 0 AND discount_value <= 100)",
            name="offer_percentage",
        ),
        sa.CheckConstraint(
            "discount_type IN ('PERCENTAGE','FLAT_AMOUNT','BOGO','FREE_ITEM','SPECIAL_PRICE')",
            name="offer_discount_type",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','PENDING_APPROVAL','ACTIVE','PAUSED',"
            "'REJECTED','EXPIRED','ARCHIVED')",
            name="offer_status",
        ),
        sa.CheckConstraint(
            "discount_value >= 0 AND minimum_purchase >= 0 "
            "AND (maximum_discount IS NULL OR maximum_discount > 0)",
            name="offer_money",
        ),
        sa.CheckConstraint("expires_at > starts_at", name="offer_dates"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["store_id", "merchant_id"],
            ["stores.id", "stores.merchant_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_offers_category_id"), "offers", ["category_id"], unique=False)
    op.create_index(op.f("ix_offers_expires_at"), "offers", ["expires_at"], unique=False)
    op.create_index(op.f("ix_offers_merchant_id"), "offers", ["merchant_id"], unique=False)
    op.create_index(op.f("ix_offers_status"), "offers", ["status"], unique=False)
    op.create_index(
        "ix_offers_status_dates", "offers", ["status", "starts_at", "expires_at"], unique=False
    )
    op.create_index(op.f("ix_offers_store_id"), "offers", ["store_id"], unique=False)
    op.alter_column("audit_events", "merchant_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM background_jobs WHERE kind = 'offer.expire'")
    op.execute("DELETE FROM audit_events WHERE merchant_id IS NULL")
    op.alter_column("audit_events", "merchant_id", existing_type=sa.UUID(), nullable=False)
    op.drop_index(op.f("ix_offers_store_id"), table_name="offers")
    op.drop_index("ix_offers_status_dates", table_name="offers")
    op.drop_index(op.f("ix_offers_status"), table_name="offers")
    op.drop_index(op.f("ix_offers_merchant_id"), table_name="offers")
    op.drop_index(op.f("ix_offers_expires_at"), table_name="offers")
    op.drop_index(op.f("ix_offers_category_id"), table_name="offers")
    op.drop_table("offers")
    op.drop_index("uq_category_name", table_name="categories")
    op.drop_table("categories")
