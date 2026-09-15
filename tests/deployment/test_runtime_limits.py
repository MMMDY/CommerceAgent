"""Static assertions for the documented single-host resource envelope."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_compose_and_entrypoint_pin_runtime_limits() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    db = (ROOT / "src" / "db.py").read_text(encoding="utf-8")
    runner = (ROOT / "src" / "harness" / "run_driver.py").read_text(encoding="utf-8")

    assert 'memory: 384M' in compose
    assert 'memory: 256M' in compose
    assert 'cpus: "1.5"' in compose
    assert 'cpus: "0.75"' in compose
    assert '"--workers", "1"' in dockerfile
    assert "pool_size=5" in db
    assert "max_overflow=2" in db
    assert "ThreadPoolExecutor(max_workers=1" in runner
