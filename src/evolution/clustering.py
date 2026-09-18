"""Stable, privacy-preserving failure cluster keys."""

# ruff: noqa: E501

from __future__ import annotations

from hashlib import sha256


def cluster_key(*, category: str, route: str | None, reason_code: str | None) -> str:
    material = "|".join((category[:64], (route or "unknown")[:128], (reason_code or "unknown")[:128]))
    return "cluster:" + sha256(material.encode()).hexdigest()[:32]


__all__ = ["cluster_key"]
