from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


def database_ready(engine: Engine) -> bool:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    required = ScriptDirectory.from_config(config).get_current_head()
    try:
        with engine.connect() as connection:
            actual = connection.scalar(text("SELECT version_num FROM alembic_version"))
            postgis = connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')")
            )
        return actual == required and bool(postgis)
    except SQLAlchemyError:
        return False
