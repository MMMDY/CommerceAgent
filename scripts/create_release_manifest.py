#!/usr/bin/env python3
"""Create a secret-free, content-addressed release manifest.

The manifest is intentionally generated from Git's tracked files.  It records
the exact source commit and hashes of runtime, dependency, migration, prompt,
workflow, policy, tool-schema, dataset and rubric inputs without copying any
credentials or environment values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".env", ".env.example"}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    return result.stdout.strip()


def _tracked_files() -> list[str]:
    names = _git("ls-files", "-z")
    files = [name for name in names.split("\x00") if name]
    return sorted(name for name in files if name not in EXCLUDED_PARTS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _is_clean() -> bool:
    return not bool(_git("status", "--porcelain"))


def build_manifest(*, require_clean: bool) -> dict[str, Any]:
    clean = _is_clean()
    if require_clean and not clean:
        raise RuntimeError("worktree_not_clean")
    files: dict[str, str] = {}
    for name in _tracked_files():
        path = ROOT / name
        if path.is_file():
            files[name] = _sha256(path)
    # Include migration files present in a dirty workspace as well.  This
    # keeps ``--allow-dirty`` useful during development and, more importantly,
    # prevents a lexicographic filename from masquerading as Alembic's graph
    # head when revisions are branched or renamed.
    migration_root = ROOT / "infra" / "migrations" / "versions"
    for path in migration_root.glob("*.py"):
        name = path.relative_to(ROOT).as_posix()
        files.setdefault(name, _sha256(path))
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    migration_head = script.get_current_head()
    head_script = script.get_revision(migration_head) if migration_head else None
    migration_head_filename = (
        Path(head_script.path).relative_to(ROOT).as_posix() if head_script is not None else None
    )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": _git("rev-parse", "HEAD"),
        "worktree_clean_at_generation": clean,
        "migration_head_filename": migration_head_filename,
        "migration_head": migration_head,
        "files": files,
        "secret_policy": "credentials and .env values are excluded; only content hashes are stored",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    try:
        manifest = build_manifest(require_clean=not args.allow_dirty)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(f"release-manifest failed: {error}") from error
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(json.dumps({"output": str(output), "source_commit": manifest["source_commit"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
