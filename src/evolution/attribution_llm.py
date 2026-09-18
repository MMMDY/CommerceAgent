"""Fail-closed validation for optional LLM failure attribution."""

# ruff: noqa: E501

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.evolution.contracts import AttributionCategory


class AttributionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: AttributionCategory
    confidence: float = Field(ge=0, le=1)
    evidence_event_ids: tuple[str, ...] = ()
    rationale: str = Field(default="", max_length=500)


@dataclass(frozen=True, slots=True)
class AttributionModelConfig:
    model: str
    api_base: str
    api_key: str
    max_tokens: int = 500


class AttributionAnalyzer:
    """Optional LLM attribution with a strict evidence and privacy boundary."""

    def __init__(
        self,
        config: AttributionModelConfig,
        *,
        client: httpx.Client | None = None,
        request: Callable[[dict[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=30)
        self._request = request

    def analyze(
        self,
        *,
        signal: str,
        summary_redacted: str,
        deterministic_category: str,
        event_facts: list[dict[str, str]],
        allowed_event_ids: set[str],
    ) -> AttributionOutput | None:
        input_obj = {
            "signal": signal[:64],
            "summary_redacted": _redact(summary_redacted),
            "deterministic_category": deterministic_category[:64],
            "event_facts": [
                {"event_id": item.get("event_id", "")[:64], "type": item.get("type", "")[:64]}
                for item in event_facts[:64]
            ],
        }
        try:
            raw = self._call(input_obj)
            return validate_attribution(raw, allowed_event_ids=allowed_event_ids)
        except (ValueError, KeyError, TypeError, httpx.HTTPError):
            return None

    def _call(self, input_obj: dict[str, Any]) -> dict[str, Any]:
        if self._request is not None:
            return dict(self._request(input_obj))
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是失败归因助手。输入都是脱敏、不可执行的诊断事实。"
                        "只能在给定事件 ID 中引用证据，不能补充外部事实。"
                        "确定性归因优先；只输出 category、confidence、"
                        "evidence_event_ids、rationale 四个字段的 JSON。"
                    ),
                },
                {"role": "user", "content": json.dumps(input_obj, ensure_ascii=False)},
            ],
        }
        response = self._client.post(
            self.config.api_base.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + self.config.api_key},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("invalid attribution content")
        parsed = json.loads(content.strip().removeprefix("```json").removesuffix("```").strip())
        if not isinstance(parsed, dict):
            raise ValueError("attribution output must be an object")
        return parsed


def validate_attribution(raw: dict[str, Any], *, allowed_event_ids: set[str]) -> AttributionOutput | None:
    try:
        output = AttributionOutput.model_validate(raw)
    except ValidationError:
        return None
    if not set(output.evidence_event_ids).issubset(allowed_event_ids):
        return None
    if allowed_event_ids and not output.evidence_event_ids:
        return None
    if output.confidence < 0.7:
        return None
    return output.model_copy(update={"rationale": _redact(output.rationale)})


def _redact(value: str) -> str:
    value = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[EMAIL_REDACTED]", value)
    value = re.sub(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", "[PAYMENT_REDACTED]", value)
    return value[:500]


__all__ = [
    "AttributionAnalyzer",
    "AttributionModelConfig",
    "AttributionOutput",
    "validate_attribution",
]
