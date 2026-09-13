"""Run Alembic with the migration-only database URL."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from src.config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.database_migration_url is None:
        raise SystemExit("DATABASE_MIGRATION_URL is required for migrations")

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_migration_url.get_secret_value())
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
