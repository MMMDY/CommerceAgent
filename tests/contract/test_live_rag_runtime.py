"""PostgreSQL-backed RAG execution contract for the live evaluation runtime."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine

from src.config import Settings
from src.harness.live_runtime import LiveCaseRuntime
from src.harness.schema import RuntimeCaseInput
from src.models.gateway import ModelDecision, ModelGateway
from src.protocols import (
    Decision,
    DecisionType,
    IntentClassification,
    PromptView,
    RequestDomain,
    RequestRiskLevel,
    RiskHint,
    RoutingPromptView,
    TokenUsage,
)
from src.rag.retrieval import KnowledgeRetriever
from src.repositories.knowledge import KnowledgeRepository
from src.tools.adapters.knowledge import KnowledgeToolAdapter


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


class _ContractLiveGateway(ModelGateway):
    provider = "contract_live"
    model_name = "contract_live_model"
    config_hash = "sha256:contract-live-agent"
    classifier_config_hash = "sha256:contract-live-classifier"

    def __init__(self) -> None:
        self.decisions = 0

    def classify(self, _prompt: RoutingPromptView) -> IntentClassification:
        return IntentClassification(
            intent="shipping_costs",
            risk_hint=RiskHint.READ_ONLY,
            route_hint="shipping_policy",
            confidence=1.0,
            domain=RequestDomain.COMMERCE,
            request_risk_level=RequestRiskLevel.LOW,
        )

    def decide(self, prompt: PromptView) -> ModelDecision:
        self.decisions += 1
        if self.decisions == 1:
            decision = Decision(
                type=DecisionType.CALL_TOOL,
                intent="shipping_costs",
                route="shipping_policy",
                confidence=1.0,
                tool="retrieve_knowledge",
                args={"query": "运费是多少"},
            )
        else:
            assert prompt.evidence_ids
            decision = Decision(
                type=DecisionType.RESPOND,
                intent="shipping_costs",
                route="shipping_policy",
                confidence=1.0,
                response="根据政策，普通配送免运费。",
                evidence_ids=(prompt.evidence_ids[0],),
            )
        return ModelDecision(
            decision=decision,
            latency_ms=1,
            token_usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )

    def conservative_decision_token_charge(self) -> int:
        return 15


def test_live_runtime_calls_postgres_retrieve_knowledge_and_carries_evidence(
    engine: Engine,
) -> None:
    tenant_id = "contract-live-rag-" + os.urandom(8).hex()
    repository = KnowledgeRepository(engine)
    document_id = repository.add_document(
        tenant_id=tenant_id,
        topic="shipping",
        version="contract-v1",
        source_uri="manual://contract/shipping",
        content_hash="sha256:" + os.urandom(16).hex(),
        effective_from=datetime.now(UTC),
    )
    repository.add_chunk(
        document_id=document_id,
        chunk_no=0,
        text_value="普通配送免运费，偏远地区配送政策另行说明。",
        text_hash="sha256:" + os.urandom(16).hex(),
        index_version="contract-v1",
    )

    runtime = LiveCaseRuntime(
        settings=Settings(_env_file=None, model_max_tokens=32),
        tenant_id=tenant_id,
        gateway=_ContractLiveGateway(),
        knowledge_adapter=KnowledgeToolAdapter(
            repository,
            KnowledgeRetriever(),
        ),
    )
    case = RuntimeCaseInput(
        case_id="contract_live_rag_001",
        locale="zh-CN",
        messages=({"role": "user", "content": "运费是多少"},),
    )

    trace = runtime.execute_case(
        case=case,
        fixture={},
        timeout_seconds=2,
        cancelled=lambda: False,
    )

    assert trace.status == "complete"
    assert trace.tools_called == ("retrieve_knowledge",)
    assert len(trace.evidence_ids) == 1
    assert trace.evidence_ids[0].startswith("knowledge:")
    assert trace.response == "根据政策，普通配送免运费。"
