"""Database engine and readiness helpers."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from src.config import get_settings

EXPECTED_ALEMBIC_REVISION = "20260913_0005"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=2,
        pool_timeout=5,
    )


def check_ready() -> tuple[bool, str]:
    """Return a safe readiness status without exposing connection details."""

    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    except (RuntimeError, SQLAlchemyError):
        return False, "database_or_migration_unavailable"

    if revision != EXPECTED_ALEMBIC_REVISION:
        return False, "migration_not_at_expected_revision"
    return True, "ready"
