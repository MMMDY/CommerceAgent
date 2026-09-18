from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from scripts.create_release_manifest import build_manifest


def test_release_manifest_is_content_addressed_and_secret_free() -> None:
    manifest = build_manifest(require_clean=False)
    assert manifest["source_commit"]
    files = manifest["files"]
    migration_files = sorted(
        name
        for name in files
        if name.startswith("infra/migrations/versions/") and name.endswith(".py")
    )
    assert migration_files
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    head = script.get_current_head()
    head_script = script.get_revision(head)
    assert head_script is not None
    expected_filename = Path(head_script.path).relative_to(Path.cwd()).as_posix()
    assert manifest["migration_head_filename"] == expected_filename
    assert manifest["migration_head"] == head
    assert expected_filename in files
    assert "pyproject.toml" in files
    assert "evals/commerce_bench_zh/cases.jsonl" in files
    assert ".env" not in files
    assert all(value.startswith("sha256:") for value in files.values())
