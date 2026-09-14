"""In-memory immutable view of published workflow definitions."""

from __future__ import annotations

from dataclasses import dataclass


class WorkflowRegistryError(ValueError):
    """A run asked for an absent or ambiguous published workflow."""


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    workflow_id: str
    version: str
    steps: tuple[str, ...]


class WorkflowRegistry:
    def __init__(self, definitions: tuple[WorkflowDefinition, ...]) -> None:
        self._definitions = {(item.workflow_id, item.version): item for item in definitions}
        if len(self._definitions) != len(definitions):
            raise WorkflowRegistryError("duplicate workflow definition")

    def get(self, *, workflow_id: str, version: str) -> WorkflowDefinition:
        try:
            return self._definitions[(workflow_id, version)]
        except KeyError as error:
            raise WorkflowRegistryError("workflow version is unavailable") from error
