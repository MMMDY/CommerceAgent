"""Immutable workflow and policy version definitions."""

# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class VersionDefinition:
    identifier: str
    version: str
    definition: dict[str, object]
    status: str


class VersionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def publish_workflow(self, *, workflow_id: str, version: str, definition: dict[str, object],
                         definition_hash: str, created_at: datetime) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO domain.workflow_versions "
                "(workflow_id, version, definition_json, definition_hash, status, created_at, activated_at) "
                "VALUES (:identifier, :version, CAST(:definition AS jsonb), :hash, 'active', :created_at, :created_at)"),
                {"identifier": workflow_id, "version": version, "definition": json.dumps(definition),
                 "hash": definition_hash, "created_at": created_at})

    def workflow(self, *, workflow_id: str, version: str) -> VersionDefinition | None:
        return self._load(table="workflow_versions", id_column="workflow_id", json_column="definition_json",
            identifier=workflow_id, version=version)

    def publish_policy(self, *, policy_id: str, version: str, rules: dict[str, object], rules_hash: str,
                       effective_from: datetime, created_at: datetime) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO domain.policy_versions "
                "(policy_id, version, rules_json, rules_hash, effective_from, status, created_at) "
                "VALUES (:identifier, :version, CAST(:definition AS jsonb), :hash, :effective_from, 'active', :created_at)"),
                {"identifier": policy_id, "version": version, "definition": json.dumps(rules), "hash": rules_hash,
                 "effective_from": effective_from, "created_at": created_at})

    def policy(self, *, policy_id: str, version: str) -> VersionDefinition | None:
        return self._load(table="policy_versions", id_column="policy_id", json_column="rules_json",
            identifier=policy_id, version=version)

    def _load(self, *, table: str, id_column: str, json_column: str, identifier: str,
              version: str) -> VersionDefinition | None:
        statement = text(f"SELECT {id_column}, version, {json_column}, status FROM domain.{table} "
            f"WHERE {id_column} = :identifier AND version = :version")
        with self._engine.connect() as connection:
            row = connection.execute(statement, {"identifier": identifier, "version": version}).one_or_none()
        return VersionDefinition(*tuple(row)) if row is not None else None
