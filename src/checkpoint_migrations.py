"""Explicit forward migrations for persisted checkpoint state."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any


class CheckpointMigrationError(ValueError):
    """A persisted state cannot safely be interpreted by this runtime."""


Migration = Callable[[dict[str, Any]], dict[str, Any]]


class CheckpointStateMigrator:
    """Registry of adjacent, deterministic state migrations.

    Migrations receive and return ordinary JSON-compatible dictionaries.  The
    registry never mutates a state object supplied by a repository caller.
    """

    def __init__(self, current_version: str) -> None:
        self._current_version = current_version
        self._migrations: dict[str, tuple[str, Migration]] = {}

    @property
    def current_version(self) -> str:
        return self._current_version

    def register(self, *, from_version: str, to_version: str, migration: Migration) -> None:
        if from_version == to_version or from_version in self._migrations:
            raise CheckpointMigrationError("checkpoint migration is not uniquely forward")
        self._migrations[from_version] = (to_version, migration)

    def migrate(self, *, version: str, state: dict[str, Any]) -> dict[str, Any]:
        if version == self._current_version:
            return deepcopy(state)
        result = deepcopy(state)
        seen: set[str] = set()
        while version != self._current_version:
            if version in seen or version not in self._migrations:
                raise CheckpointMigrationError("checkpoint migration path is unavailable")
            seen.add(version)
            next_version, migration = self._migrations[version]
            result = migration(result)
            if not isinstance(result, dict):
                raise CheckpointMigrationError("checkpoint migration must return an object")
            version = next_version
        return result
