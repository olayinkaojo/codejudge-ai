from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def database_engine():
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        pool_timeout=5,
        connect_args={"connect_timeout": 5},
    )


@lru_cache
def session_factory():
    engine = database_engine()
    return sessionmaker(engine, expire_on_commit=False)


def get_db():
    try:
        session = session_factory()()
    except Exception as exc:
        from app.database_status import report_failure

        report_failure(exc, "database_session")
        raise HTTPException(503, "Database unavailable") from None
    try:
        yield session
    finally:
        session.close()
