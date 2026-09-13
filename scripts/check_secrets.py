#!/usr/bin/env python3
"""Fail closed on likely secret leakage without printing secret values."""

from __future__ import annotations

import argparse
import re
import stat
import subprocess
import sys
from pathlib import Path

PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:api[_-]?key|authorization)\s*[:=]\s*['\"]?[A-Za-z0-9._-]{16,}", re.I),
)
ALLOWED_ENV_KEYS = {
    "APP_ENV",
    "APP_BIND",
    "DEMO_MODE",
    "DEMO_ACTOR_ALLOWLIST",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_MIGRATION_USER",
    "POSTGRES_MIGRATION_PASSWORD",
    "POSTGRES_RUNTIME_USER",
    "POSTGRES_RUNTIME_PASSWORD",
    "DATABASE_MIGRATION_URL",
    "DATABASE_URL",
    "MODEL",
    "API_BASE",
    "API_KEY",
    "JUDGE_MODEL",
    "JUDGE_API_BASE",
    "JUDGE_API_KEY",
}


def git_lines(arguments: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError("unable to inspect Git metadata")
    return [line for line in completed.stdout.splitlines() if line]


def inspect_files(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.is_file() or path.name == ".env":
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            findings.append(str(path))
            continue
        if any(pattern.search(content) for pattern in PATTERNS):
            findings.append(str(path))
    return findings


def inspect_env_policy(path: Path) -> list[str]:
    if not path.exists():
        return []
    findings: list[str] = []
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        findings.append(".env permission is not 0600")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and any(
            key in stripped for key in ("KEY=", "TOKEN=", "PASSWORD=")
        ):
            findings.append(".env contains a commented credential assignment")
            break
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key not in ALLOWED_ENV_KEYS:
                findings.append(".env contains an unknown variable name")
                break
    return findings


def inspect_history() -> list[str]:
    completed = subprocess.run(
        ["git", "log", "-p", "--all", "--no-ext-diff"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return ["Git history scan unavailable"]
    if any(pattern.search(completed.stdout) for pattern in PATTERNS):
        return ["Git history contains a likely secret"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--tracked-only", action="store_true")
    parser.add_argument("--env-policy", type=Path)
    parser.add_argument("--frontend", type=Path)
    parser.add_argument("--compose-service")
    parser.add_argument("--git-history", action="store_true")
    parser.add_argument("--redact", action="store_true")
    args = parser.parse_args()

    findings: list[str] = []
    if args.repository:
        if not args.tracked_only:
            parser.error("--repository requires --tracked-only")
        paths = [args.repository / item for item in git_lines(["ls-files"])]
        findings.extend(inspect_files(paths))
    if args.frontend:
        findings.extend(inspect_files(list(args.frontend.rglob("*"))))
    if args.env_policy:
        findings.extend(inspect_env_policy(args.env_policy))
    if args.git_history:
        findings.extend(inspect_history())
    if args.compose_service:
        image = subprocess.run(
            ["docker", "compose", "images", "-q", args.compose_service],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not image:
            findings.append("compose service image is unavailable")

    if findings:
        for finding in findings:
            print(f"secret-check failed: {finding}", file=sys.stderr)
        return 1
    print("secret-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
