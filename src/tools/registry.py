"""Immutable name-and-version tool registry."""

from __future__ import annotations

from src.protocols import ToolContext, ToolSpec


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

    def resolve(
        self,
        *,
        name: str,
        version: str,
        context: ToolContext,
        require_model_visible: bool = False,
    ) -> ToolSpec:
        """Resolve one spec and enforce its trusted workflow/step boundary."""

        spec = self.get(name=name, version=version)
        if require_model_visible and not spec.model_visible:
            raise ToolRegistryError("tool is not model visible")
        if spec.allowed_workflows:
            workflow = (
                f"{context.workflow_id}@{context.workflow_version}"
                if context.workflow_id is not None and context.workflow_version is not None
                else None
            )
            if workflow not in spec.allowed_workflows:
                raise ToolRegistryError("tool is not allowed in the current workflow")
        if spec.allowed_steps and context.current_step not in spec.allowed_steps:
            raise ToolRegistryError("tool is not allowed in the current step")
        if not set(spec.required_scopes).issubset(context.scopes):
            raise ToolRegistryError("tool scopes are unavailable")
        return spec

    def model_visible_names(self) -> frozenset[str]:
        return frozenset(spec.name for spec in self._entries.values() if spec.model_visible)

    def __len__(self) -> int:
        return len(self._entries)
