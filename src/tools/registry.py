"""Immutable name-and-version tool registry."""

from __future__ import annotations

from src.protocols import ToolSpec


class ToolRegistryError(ValueError):
    """A registry lookup or registration violated the frozen catalog."""


class ToolRegistry:
    def __init__(self, specs: tuple[ToolSpec, ...]) -> None:
        entries = {(spec.name, spec.version): spec for spec in specs}
        if len(entries) != len(specs):
            raise ToolRegistryError("duplicate tool name and version")
        self._entries = entries

    def get(self, *, name: str, version: str) -> ToolSpec:
        try:
            return self._entries[(name, version)]
        except KeyError as error:
            raise ToolRegistryError("unknown tool version") from error

    def model_visible_names(self) -> frozenset[str]:
        return frozenset(spec.name for spec in self._entries.values() if spec.model_visible)

    def __len__(self) -> int:
        return len(self._entries)
