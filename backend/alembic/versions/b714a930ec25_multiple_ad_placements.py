"""Add homepage and above-offer advertisement placements."""

import sqlalchemy as sa

from alembic import op

revision = "b714a930ec25"
down_revision = "47cc4096c40d"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("advertisement_placement", "advertisements", type_="check")
    op.create_check_constraint(
        "advertisement_placement",
        "advertisements",
        "placement IN ('BELOW_HERO','ABOVE_OFFERS','BELOW_DAILY','BELOW_OFFERS')",
    )


def downgrade():
    # Do not silently move a published campaign to another location.
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM advertisements WHERE placement IN ('BELOW_HERO','ABOVE_OFFERS')"
        )
    ):
        raise RuntimeError("Move advertisements out of the new placements before downgrading.")
    op.drop_constraint("advertisement_placement", "advertisements", type_="check")
    op.create_check_constraint(
        "advertisement_placement", "advertisements", "placement IN ('BELOW_DAILY','BELOW_OFFERS')"
    )
