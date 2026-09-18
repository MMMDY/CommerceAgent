#!/usr/bin/env python3
"""Remove expired correction text using the migration/maintenance connection.

The application runtime role intentionally has no DELETE privilege on feedback
or failure tables.  Run this command from a maintenance job with
``DATABASE_MIGRATION_URL``; it retains feedback rows, hashes, ratings and
aggregates while clearing only expired correction text.
"""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine, text

from src.config import get_settings


def purge(*, database_url: str) -> int:
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "UPDATE feedback.user_feedback "
                "SET correction_redacted = NULL, expires_at = NULL "
                "WHERE correction_redacted IS NOT NULL AND expires_at IS NOT NULL "
                "AND expires_at <= now() RETURNING feedback_id"
            )
        ).all()
    engine.dispose()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        help="maintenance connection; defaults to DATABASE_MIGRATION_URL",
    )
    args = parser.parse_args()
    settings = get_settings()
    database_url = args.database_url or (
        settings.database_migration_url.get_secret_value()
        if settings.database_migration_url is not None
        else None
    )
    if not database_url:
        raise SystemExit("DATABASE_MIGRATION_URL is required")
    print({"purged_correction_rows": purge(database_url=database_url)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
