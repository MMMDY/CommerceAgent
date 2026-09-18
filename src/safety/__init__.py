"""Fail-closed safety detection and response contracts."""

from src.safety.contracts import SafetyAssessment, SafetyCategory, SafetyDisposition
from src.safety.detector import detect
from src.safety.responses import safe_response_for
from src.safety.router import SafetyRouter

__all__ = [
    "SafetyAssessment",
    "SafetyCategory",
    "SafetyDisposition",
    "SafetyRouter",
    "detect",
    "safe_response_for",
]
