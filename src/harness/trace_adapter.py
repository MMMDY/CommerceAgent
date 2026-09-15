"""Compatibility exports for normalized runtime traces."""

from src.harness.runtime import RuntimeTrace, TraceAdapter
from src.harness.schema import NormalizedTrace

__all__ = ["NormalizedTrace", "RuntimeTrace", "TraceAdapter"]
