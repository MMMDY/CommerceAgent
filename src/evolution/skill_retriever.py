"""Deterministic, bounded Skill matching used by Shadow/Canary only."""

# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class SkillMatch:
    skill_id: str
    skill_version_id: str
    score: float
    scope_type: str
    scope_value: str
    mode: str
    strategy_view: dict[str, Any]


def match_skill(*, text_value: str, trigger: dict[str, Any]) -> float:
    """Return a conservative lexical score; no match ever authorizes a tool."""
    keywords = trigger.get("keywords", [])
    if not isinstance(keywords, list) or not keywords:
        return 0.0
    normalized = text_value.casefold()
    hits = sum(1 for keyword in keywords[:32] if isinstance(keyword, str) and keyword.casefold() in normalized)
    return min(1.0, hits / max(1, min(len(keywords), 8)))


def select_skill(
    *,
    text_value: str,
    tenant_id: str,
    route: str | None,
    candidates: list[dict[str, Any]],
    mode: str = "active",
    minimum_score: float = 0.75,
) -> SkillMatch | None:
    """Choose one tenant-safe, narrowest matching Skill.

    The returned strategy is an allowlisted view.  Definition fields such as
    tools, code, URLs, SQL, and raw failure text are never passed through.
    """

    if mode not in {"shadow", "canary", "active"}:
        raise ValueError("invalid_skill_match_mode")
    options: list[tuple[tuple[float, int, str], SkillMatch]] = []
    scope_rank = {"route": 0, "tenant": 1, "global": 2}
    for candidate in candidates:
        if candidate.get("tenant_id") != tenant_id:
            continue
        status = str(candidate.get("status", ""))
        if mode == "active" and status not in {"ACTIVE", "CANARY"}:
            continue
        if mode == "canary" and status != "CANARY":
            continue
        if mode == "shadow" and status not in {"APPROVED", "CANARY", "ACTIVE"}:
            continue
        if _expired(candidate.get("expires_at")):
            continue
        scope_type = str(candidate.get("scope_type", ""))
        scope_value = str(candidate.get("scope_value", ""))
        if scope_type not in scope_rank or not _scope_matches(
            scope_type, scope_value, tenant_id, route
        ):
            continue
        score = match_skill(text_value=text_value, trigger=_dict(candidate.get("trigger")))
        if score < minimum_score:
            continue
        skill_id = candidate.get("skill_id")
        version_id = candidate.get("skill_version_id")
        if not isinstance(skill_id, str) or not isinstance(version_id, str):
            continue
        match = SkillMatch(
            skill_id=skill_id,
            skill_version_id=version_id,
            score=score,
            scope_type=scope_type,
            scope_value=scope_value,
            mode=mode,
            strategy_view=_strategy_view(candidate.get("strategy")),
        )
        options.append(((-score, scope_rank[scope_type], skill_id), match))
    if not options:
        return None
    options.sort(key=lambda item: item[0])
    return options[0][1]


def select_skill_from_registry(
    *,
    text_value: str,
    tenant_id: str,
    route: str | None,
    candidates_loader: Callable[[], list[dict[str, Any]]],
    mode: str = "active",
    minimum_score: float = 0.75,
) -> SkillMatch | None:
    """Read the optional registry fail-closed and preserve ordinary routing.

    Registry I/O is deliberately isolated from the Safety Router and business
    route.  Any unavailable/invalid registry result becomes a miss; it cannot
    grant a Skill and it cannot block the normal route.
    """

    try:
        candidates = candidates_loader()
    except Exception:
        return None
    return select_skill(
        text_value=text_value,
        tenant_id=tenant_id,
        route=route,
        candidates=candidates,
        mode=mode,
        minimum_score=minimum_score,
    )


def _scope_matches(
    scope_type: str, scope_value: str, tenant_id: str, route: str | None
) -> bool:
    if scope_type == "global":
        return True
    if scope_type == "route":
        return route is not None and scope_value == route
    return scope_type == "tenant" and scope_value == tenant_id


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _expired(value: Any) -> bool:
    """Fail closed for an expired candidate even when called without SQL."""

    if value is None:
        return False
    if isinstance(value, datetime):
        expires_at = value
    elif isinstance(value, str):
        try:
            expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return True
    else:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def _strategy_view(value: Any) -> dict[str, Any]:
    strategy = _dict(value)
    allowed = {"response_policy", "allowed_decisions", "forbidden_tools", "ttl_seconds"}
    return {key: strategy[key] for key in allowed if key in strategy}


__all__ = ["SkillMatch", "match_skill", "select_skill", "select_skill_from_registry"]
