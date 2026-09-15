"""Minimal structured JSON logging with mandatory redaction."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.telemetry.trace import _sanitize


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for field in ("request_id", "run_id", "step_id", "tool", "error", "version"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(_sanitize(payload), ensure_ascii=False, sort_keys=True)


def configure_json_logging(level: int = logging.INFO) -> None:
    """Configure one process-wide handler without changing application logic."""

    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        root.addHandler(handler)


__all__ = ["JsonLogFormatter", "configure_json_logging"]
