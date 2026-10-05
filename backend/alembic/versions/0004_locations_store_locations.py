"""store_locations"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.locations.spatial import GeographyPoint

revision = "0004_locations"
down_revision = "0003_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stores", sa.Column("area", sa.String(length=100), server_default="", nullable=False)
    )
    op.add_column(
        "stores", sa.Column("state", sa.String(length=100), server_default="", nullable=False)
    )
    op.add_column(
        "stores", sa.Column("country", sa.String(length=2), server_default="IN", nullable=False)
    )
    op.add_column(
        "stores", sa.Column("postal_code", sa.String(length=20), server_default="", nullable=False)
    )
    op.add_column(
        "stores", sa.Column("phone", sa.String(length=30), server_default="", nullable=False)
    )
    op.add_column(
        "stores",
        sa.Column("timezone", sa.String(length=100), server_default="Asia/Kolkata", nullable=False),
    )
    op.add_column("stores", sa.Column("latitude", sa.Double(), nullable=True))
    op.add_column("stores", sa.Column("longitude", sa.Double(), nullable=True))
    op.add_column(
        "stores",
        sa.Column(
            "location",
            GeographyPoint(),
            sa.Computed(
                "ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography", persisted=True
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "stores", sa.Column("status", sa.String(length=10), server_default="ACTIVE", nullable=False)
    )
    op.add_column(
        "stores",
        sa.Column(
            "hours", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.add_column("stores", sa.Column("revision", sa.Integer(), server_default="1", nullable=False))
    op.add_column(
        "stores",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "stores",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_stores_location", "stores", ["location"], unique=False, postgresql_using="gist"
    )

    op.create_check_constraint("store_status", "stores", "status IN ('ACTIVE','INACTIVE')")
    op.create_check_constraint(
        "store_coordinate_pair", "stores", "(latitude IS NULL) = (longitude IS NULL)"
    )
    op.create_check_constraint(
        "store_coordinate_bounds",
        "stores",
        "latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180",
    )


def downgrade() -> None:
    op.drop_constraint("store_coordinate_bounds", "stores", type_="check")
    op.drop_constraint("store_coordinate_pair", "stores", type_="check")
    op.drop_constraint("store_status", "stores", type_="check")
    op.drop_index("ix_stores_location", table_name="stores", postgresql_using="gist")
    op.drop_column("stores", "updated_at")
    op.drop_column("stores", "created_at")
    op.drop_column("stores", "revision")
    op.drop_column("stores", "hours")
    op.drop_column("stores", "status")
    op.drop_column("stores", "location")
    op.drop_column("stores", "longitude")
    op.drop_column("stores", "latitude")
    op.drop_column("stores", "timezone")
    op.drop_column("stores", "phone")
    op.drop_column("stores", "postal_code")
    op.drop_column("stores", "country")
    op.drop_column("stores", "state")
    op.drop_column("stores", "area")
