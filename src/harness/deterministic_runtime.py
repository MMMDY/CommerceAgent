"""Deterministic Runtime assembly for the Phase 2 hard-eval Harness.

The fixture is an independent input to a fake model and fake tools.  It is not
derived from, and its schema cannot contain, evaluation gold outcomes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import ConfigDict, Field, ValidationError, model_validator

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.harness.run_driver import AgentLoopCaseRuntime, AgentLoopPlan
from src.harness.runtime import RuntimeTrace
from src.harness.schema import RuntimeCaseInput
from src.models.gateway import DeterministicFakeModel
from src.orchestration.pipeline import PromptBuilder, StepPipeline
from src.protocols import (
    Contract,
    Decision,
    DecisionType,
    Message,
    PromptView,
    RunContext,
    RunStatus,
    SlotValue,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


class RuntimeFixtureError(ValueError):
    """A deterministic runtime fixture is missing or violates its contract."""


class RuntimePlanFixture(Contract):
    """Trusted runtime boundary supplied independently of an eval case's gold."""

    route: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    workflow_version: str = Field(default="1", min_length=1, max_length=64)
    current_step: str = Field(default="fixture_step", min_length=1, max_length=128)
    system_policy_version: str = Field(default="fixture-v1", min_length=1, max_length=128)
    allowed_decisions: tuple[DecisionType, ...]
    allowed_tools: tuple[str, ...] = ()
    trusted_evidence_ids: tuple[str, ...] = ()
    known_slots: dict[str, SlotValue] = Field(default_factory=dict)
    required_slots: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    token_budget_remaining: int | None = Field(default=None, ge=0)
    trace_next_action: str | None = Field(default=None, min_length=1, max_length=128)


class DeterministicToolFixture(Contract):
    spec: ToolSpec
    result: ToolResult

    @model_validator(mode="after")
    def validate_identity(self) -> DeterministicToolFixture:
        if self.spec.version != "1":
            raise ValueError("AgentLoop fixtures currently require tool version 1")
        if (self.result.tool_name, self.result.tool_version) != (
            self.spec.name,
            self.spec.version,
        ):
            raise ValueError("fake tool result identity does not match its specification")
        return self


class DeterministicCaseFixture(Contract):
    """One fake-model step and its trusted execution boundary for a case ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    plan: RuntimePlanFixture
    decision: Decision
    tools: tuple[DeterministicToolFixture, ...] = ()

    @model_validator(mode="after")
    def validate_unique_tools(self) -> DeterministicCaseFixture:
        names = tuple(tool.spec.name for tool in self.tools)
        if len(set(names)) != len(names):
            raise ValueError("duplicate fake tool name")
        return self


class RuntimeFixtureLoader:
    """Strict JSONL loader for deterministic runtime inputs."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def fixture_hash(self) -> str:
        if not self._path.is_file():
            raise RuntimeFixtureError("runtime fixture is unavailable")
        return hashlib.sha256(self._path.read_bytes()).hexdigest()

    def load(self) -> tuple[DeterministicCaseFixture, ...]:
        if not self._path.is_file():
            raise RuntimeFixtureError("runtime fixture is unavailable")
        fixtures: list[DeterministicCaseFixture] = []
        case_ids: set[str] = set()
        for number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                raise RuntimeFixtureError(f"blank runtime fixture line at {number}")
            try:
                fixture = DeterministicCaseFixture.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as error:
                raise RuntimeFixtureError(f"invalid runtime fixture at line {number}") from error
            if fixture.case_id in case_ids:
                raise RuntimeFixtureError("duplicate runtime fixture case identifier")
            case_ids.add(fixture.case_id)
            fixtures.append(fixture)
        if not fixtures:
            raise RuntimeFixtureError("runtime fixture is empty")
        return tuple(fixtures)


class DeterministicRuntimeFactory:
    """Build a fresh real AgentLoopCaseRuntime for each isolated case execution."""

    def __init__(self, fixtures: tuple[DeterministicCaseFixture, ...]) -> None:
        self._fixtures = {fixture.case_id: fixture for fixture in fixtures}
        if len(self._fixtures) != len(fixtures):
            raise RuntimeFixtureError("duplicate runtime fixture case identifier")

    def execute_case(
        self,
        *,
        case: RuntimeCaseInput,
        fixture: dict[str, object],
        timeout_seconds: float,
        cancelled: Callable[[], bool],
    ) -> RuntimeTrace:
        try:
            definition = self._fixtures[case.case_id]
        except KeyError as error:
            raise RuntimeFixtureError("runtime fixture case is unavailable") from error

        specs = tuple(tool.spec for tool in definition.tools)
        adapters = {tool.spec.name: _constant_adapter(tool.result) for tool in definition.tools}
        loop = AgentLoop(
            model=DeterministicFakeModel((definition.decision,)),
            validator=DecisionValidator(),
            registry=ToolRegistry(specs),
            executor=ToolExecutor(adapters),
        )
        runtime = AgentLoopCaseRuntime(
            loop=loop,
            planner=_FixturePlanner(definition.plan, loop=loop),
        )
        return runtime.execute_case(
            case=case,
            fixture=fixture,
            timeout_seconds=timeout_seconds,
            cancelled=cancelled,
        )


class _FixtureCheckpoints:
    def __init__(self) -> None:
        self.sequence = 0

    def checkpoint(self, **_: object) -> int:
        self.sequence += 1
        return self.sequence


class _FixturePromptBuilder(PromptBuilder):
    def __init__(self, prompt: PromptView) -> None:
        self._prompt = prompt

    def build(self, *, context: RunContext) -> PromptView:
        return self._prompt.model_copy(update={"remaining_steps": max(0, 6 - context.step_count)})


class _FixturePlanner:
    def __init__(self, plan: RuntimePlanFixture, *, loop: AgentLoop) -> None:
        self._plan = plan
        self._loop = loop

    def plan(
        self,
        *,
        case: RuntimeCaseInput,
        fixture: dict[str, object],
        timeout_seconds: float,
    ) -> AgentLoopPlan:
        conversation: list[Message] = []
        for message in case.messages:
            if message.role == "tool":
                raise RuntimeFixtureError("tool-role messages are not supported by PromptView")
            conversation.append(Message(role=message.role, content=message.content))

        run_id = uuid5(NAMESPACE_URL, f"commerce-agent:harness:{case.case_id}:run")
        conversation_id = uuid5(
            NAMESPACE_URL, f"commerce-agent:harness:{case.case_id}:conversation"
        )
        context = RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id="harness",
            actor_id="deterministic-fixture",
            workflow_id=self._plan.workflow_id,
            workflow_version=self._plan.workflow_version,
            status=RunStatus.RUNNING_READONLY,
            state=deepcopy(fixture),
        )
        prompt = PromptView(
            system_policy_version=self._plan.system_policy_version,
            workflow_id=self._plan.workflow_id,
            workflow_version=self._plan.workflow_version,
            current_step=self._plan.current_step,
            allowed_decisions=tuple(item.value for item in self._plan.allowed_decisions),
            conversation=tuple(conversation),
            known_slots=self._plan.known_slots,
            required_slots=self._plan.required_slots,
            allowed_tools=self._plan.allowed_tools,
            evidence_ids=self._plan.trusted_evidence_ids,
            remaining_steps=6,
        )
        pipeline = StepPipeline(
            step_executor=self._loop.step_executor,
            checkpoints=_FixtureCheckpoints(),
            prompt_builder=_FixturePromptBuilder(prompt),
        )
        return AgentLoopPlan(
            context=context,
            prompt=prompt,
            boundary=DecisionBoundary(
                route=self._plan.route,
                allowed_types=frozenset(self._plan.allowed_decisions),
                allowed_tools=frozenset(self._plan.allowed_tools),
                trusted_evidence_ids=frozenset(self._plan.trusted_evidence_ids),
            ),
            tool_context=ToolContext(
                request_id=uuid5(NAMESPACE_URL, f"commerce-agent:harness:{case.case_id}:request"),
                run_id=run_id,
                conversation_id=conversation_id,
                tenant_id="harness",
                actor_id="deterministic-fixture",
                scopes=self._plan.scopes,
            ),
            deadline_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
            token_budget_remaining=self._plan.token_budget_remaining,
            trace_next_action=self._plan.trace_next_action,
            pipeline=pipeline,
        )


def _constant_adapter(
    result: ToolResult,
) -> Callable[[ToolContext, dict[str, object]], ToolResult]:
    def adapter(_context: ToolContext, _arguments: dict[str, object]) -> ToolResult:
        return result.model_copy(deep=True)

    return adapter
