"""Tenant-scoped consented user feedback persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.guardrails.trust import sanitize


@dataclass(frozen=True, slots=True)
class UserFeedback:
    feedback_id: UUID
    tenant_id: str
    actor_hash: str
    run_id: UUID
    rating: str
    reason_codes: tuple[str, ...]
    correction_redacted: str | None
    correction_hash: str | None
    consent_for_improvement: bool
    idempotency_key: str
    created_at: datetime
    expires_at: datetime | None


class FeedbackRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def submit(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        run_id: UUID,
        rating: str,
        reason_codes: tuple[str, ...],
        correction: str | None,
        consent_for_improvement: bool,
        idempotency_key: str,
        ttl_days: int = 30,
    ) -> UserFeedback:
        if rating not in {"up", "down"}:
            raise ValueError("rating must be up or down")
        if not 1 <= len(idempotency_key) <= 128 or not 0 < ttl_days <= 30:
            raise ValueError("invalid feedback contract")
        if len(reason_codes) > 8 or any(len(item) > 64 for item in reason_codes):
            raise ValueError("invalid feedback reason codes")
        actor_hash = "sha256:" + sha256(actor_id.encode()).hexdigest()
        safe_correction = None
        if consent_for_improvement and correction:
            safe_correction = str(sanitize(correction))[:2000]
        correction_hash = (
            "sha256:" + sha256(safe_correction.encode()).hexdigest()
            if safe_correction
            else None
        )
        expires_at = datetime.now(UTC) + timedelta(days=ttl_days) if safe_correction else None
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "INSERT INTO feedback.user_feedback "
                    "(feedback_id, tenant_id, actor_hash, run_id, rating, reason_codes, "
                    "correction_redacted, correction_hash, consent_for_improvement, "
                    "idempotency_key, expires_at) "
                    "VALUES (:feedback_id, :tenant_id, :actor_hash, :run_id, :rating, "
                    "CAST(:reason_codes AS jsonb), :correction, :correction_hash, :consent, "
                    ":idempotency_key, "
                    ":expires_at) "
                    "ON CONFLICT (tenant_id, actor_hash, idempotency_key) DO UPDATE SET "
                    "rating = feedback.user_feedback.rating "
                    "RETURNING feedback_id, tenant_id, actor_hash, run_id, rating, reason_codes, "
                    "correction_redacted, correction_hash, consent_for_improvement, "
                    "idempotency_key, "
                    "created_at, "
                    "expires_at"
                ),
                {
                    "feedback_id": uuid4(), "tenant_id": tenant_id, "actor_hash": actor_hash,
                    "run_id": run_id, "rating": rating, "reason_codes": json.dumps(reason_codes),
                    "correction": safe_correction, "correction_hash": correction_hash,
                    "consent": consent_for_improvement,
                    "idempotency_key": idempotency_key, "expires_at": expires_at,
                },
            ).one()
        values = dict(row._mapping)
        values["reason_codes"] = tuple(str(item) for item in (values["reason_codes"] or []))
        return UserFeedback(**values)


__all__ = ["FeedbackRepository", "UserFeedback"]
