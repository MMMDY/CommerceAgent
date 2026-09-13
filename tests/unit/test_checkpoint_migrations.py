from __future__ import annotations

import pytest

from src.checkpoint_migrations import CheckpointMigrationError, CheckpointStateMigrator


def test_migrator_composes_forward_steps_without_mutating_checkpoint() -> None:
    migrator = CheckpointStateMigrator("3")
    migrator.register(
        from_version="1", to_version="2", migration=lambda state: {**state, "v2": True}
    )
    migrator.register(
        from_version="2", to_version="3", migration=lambda state: {**state, "v3": True}
    )
    state = {"v1": True}

    assert migrator.migrate(version="1", state=state) == {"v1": True, "v2": True, "v3": True}
    assert state == {"v1": True}


def test_migrator_rejects_missing_or_ambiguous_paths() -> None:
    migrator = CheckpointStateMigrator("2")
    with pytest.raises(CheckpointMigrationError, match="unavailable"):
        migrator.migrate(version="1", state={})
    migrator.register(from_version="1", to_version="2", migration=lambda state: state)
    with pytest.raises(CheckpointMigrationError, match="uniquely forward"):
        migrator.register(from_version="1", to_version="2", migration=lambda state: state)
