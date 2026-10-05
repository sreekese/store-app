from typing import Any

from sqlalchemy import create_engine, pool

from alembic import context
from app.advertisements import models as advertisement_models  # noqa: F401
from app.analytics import models as analytics_models  # noqa: F401
from app.auth.audit import SecurityEvent  # noqa: F401
from app.auth.models import AuthRateLimit, AuthSession, RefreshToken, User  # noqa: F401
from app.billing import models as billing_models  # noqa: F401
from app.core.config import Settings
from app.core.database import Base
from app.coupons import models as coupon_models  # noqa: F401
from app.daily import models as daily_models  # noqa: F401
from app.jobs.models import Job  # noqa: F401
from app.notifications import models as notification_models  # noqa: F401
from app.offers import models as offer_models  # noqa: F401
from app.profiles import models  # noqa: F401
from app.redemptions import models as redemption_models  # noqa: F401
from app.trust import models as trust_models  # noqa: F401


def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    # Extension-owned table, never managed by application migrations.
    return not (type_ == "table" and name == "spatial_ref_sys")


if context.is_offline_mode():
    context.configure(
        url=Settings().database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(Settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        # PostGIS images may also expose tiger/topology tables on search_path.
        # All application models/migrations live in public; never inspect or
        # propose removing extension tables from those additional schemas.
        connection.exec_driver_sql("SET search_path TO public")
        connection.commit()
        context.configure(
            connection=connection, target_metadata=Base.metadata, include_name=include_name
        )
        with context.begin_transaction():
            context.run_migrations()
