"""Public, prompt-safe evidence contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    """One retrieval result, containing only data safe to cite to a customer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1, max_length=160)
    document_id: str = Field(min_length=1, max_length=64)
    source_uri: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=64)
    excerpt: str = Field(min_length=1, max_length=1200)
    score: float = Field(ge=0)


class EvidencePack(BaseModel):
    """A bounded evidence set; empty is an explicit unsupported-answer signal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=512)
    evidence: tuple[Evidence, ...] = ()

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.evidence)

    @property
    def is_sufficient(self) -> bool:
        return bool(self.evidence)
