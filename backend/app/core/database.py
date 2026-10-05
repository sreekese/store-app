from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    pass


def make_engine(url: str, *, serverless: bool = False) -> Engine:
    if serverless:
        # Neon provides external pooling; don't multiply idle pools across functions.
        return create_engine(
            url,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 10,
                "prepare_threshold": None,
                "options": "-c statement_timeout=5000",
            },
        )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=5000"},
    )
