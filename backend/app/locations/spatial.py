from typing import Any

from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.types import UserDefinedType


class GeographyPoint(UserDefinedType[str]):
    """PostGIS type; coordinates are written through the generated location column."""

    cache_ok = True

    def __init__(self, *args: object) -> None:
        pass

    def get_col_spec(self, **kw: Any) -> str:
        return "geography(Point,4326)"


# Allow Alembic to reflect the extension type instead of treating it as unknown.
ischema_names["geography"] = GeographyPoint
LOCATION_SQL = "ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography"
