# Phase N3 Live RAG 与 Skill 生命周期契约证据

日期：2026-09-18

## PostgreSQL 执行证据

使用仓库提供的隔离 contract 数据库脚本完成迁移后执行：

```text
tests/contract/test_live_rag_runtime.py: 1 passed
tests/contract/test_skill_lifecycle_repository.py: 2 passed
tests/contract/ 全量: 49 passed
tests/recovery/ 全量: 17 passed
```

`test_live_rag_runtime` 使用 `LiveCaseRuntime`，连接真实 PostgreSQL 的
`KnowledgeRepository` 和 `KnowledgeToolAdapter`，插入租户隔离的知识文档/Chunk，
验证运行时实际调用 `retrieve_knowledge`、产生 `knowledge:<document>:<chunk>` evidence id，
并将该 evidence id 传入下一轮模型决策。写入和检索均通过 PostgreSQL，不使用 deterministic
fixture 代替 RAG 查询。

Skill 生命周期契约验证：

- 到期的 `PENDING_REVIEW` candidate/version 会被投影为 `EXPIRED`，且不再进入 shadow match；
- `ACTIVE` Skill rollback 后 candidate/version 变为 `ROLLED_BACK`，历史版本记录保留，active match 不再命中；
- 既有 migration contract 验证 tenant 级 kill switch 的关闭、租户隔离和恢复。

## 证据边界

该证据证明 PostgreSQL RAG adapter、TTL、rollback 和 kill switch 的代码/数据库契约；
contract 使用受控 fake gateway 验证编排调用，不证明外部真实模型质量、线上 RAG 延迟或
线上一分钟传播时延。高危人工审批、真实 Canary/Shadow 流量和 7 天基线仍未完成。
