from __future__ import annotations

from scripts.create_release_manifest import build_manifest


def test_release_manifest_is_content_addressed_and_secret_free() -> None:
    manifest = build_manifest(require_clean=False)
    assert manifest["source_commit"]
    assert manifest["migration_head"] == "20260916_0011"
    files = manifest["files"]
    assert "pyproject.toml" in files
    assert "evals/commerce_bench_zh/cases.jsonl" in files
    assert ".env" not in files
    assert all(value.startswith("sha256:") for value in files.values())
