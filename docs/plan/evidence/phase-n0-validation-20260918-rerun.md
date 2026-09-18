# Phase N0 增量验证证据

日期：2026-09-18（Asia/Shanghai）  
范围：`20260918_0023` Skill 合同兼容迁移、纠错文本 TTL 清理、前端现有垂直切片

## 结果

本次复核覆盖最新的 Agent Flow、评测、失败归因、Skill 生命周期、发布和运营可视化改动。

| 验证 | 命令 | 结果 |
|---|---|---|
| Python 全量 | `PYTHONPATH=. ./.venv/bin/pytest -q` | `367 passed, 56 skipped` |
| PostgreSQL migration + contract | `./scripts/run_phase1_contract_tests.sh` | `45 passed` |
| 前端 | `npm run lint && npm run typecheck && npm test -- --run && npm run build` | 全部通过，Vitest `7 passed` |
| Ruff | `PYTHONPATH=. ./.venv/bin/ruff check src tests apps/api/main.py` | 通过 |
| mypy | `PYTHONPATH=. ./.venv/bin/mypy src` | `Success: no issues found in 141 source files` |

## 本次新增证据

- 历史不可变 `skill_versions` 不被迁移改写，标记为 `contract_version=1`；新写入版本默认 `contract_version=2`，非法定义被 PostgreSQL 拒绝。
- global Skill 的数据库作用域约束实际拒绝非 `project/safety` 候选。
- 维护连接只清理过期 `correction_redacted`，保留反馈行和 `correction_hash`；runtime 角色无 `DELETE` 权限。
- 前端 Agent Flow 展示受理、Safety、Domain、Intent、Policy、Agent、Guardrail、回复八个阶段，并将 RAG、工具、Skill、兜底作为分支；决策卡引用白名单 event id，缺失值显示 `N/A`。
- 评测页展示 Hard Gate → Judge → Release Gate → 真人审批流程、各 rubric 平均分、Track × Rubric 热力图、attempt/case/trace 下钻；Skill 页展示生命周期漏斗、paired evaluation 和“自动评测通过 ≠ 真人审批通过”。
- 运营页展示端到端流程、Safety 命中与人工接管；失败页展示采集 → 聚类 → 归因 → 人工复核；发布详情展示 Shadow → Canary → 全量阶段和 Current/Candidate assignment。未提供真实聚合或人工标注时保持 `N/A`。
- P0 Safety 运行时事件以脱敏字段写入 append-only audit；管理员接口按 tenant 和事件类型过滤，运营页可从 Safety 聚合下钻到 Run 引用；无权限时聚合仍可展示但审计区单独显示不可用。
- Canary guard 的 P0、终态覆盖率、P95/P99 时延、P95 成本和低风险人工接管阈值均保持 fail-closed；稳定分桶、Shadow 不改变 Current、逐阶段推进和停止回滚当前版本均由单测/契约覆盖，不能替代真实线上流量证明。
- `src/harness/skill_eval.py` 已将 Skill paired eval 固定为目标 slice + safety counterexample + 全量回归三部分；目标 slice 不从失败原文复制，`tests/harness/test_skill_eval_slice.py` 验证分区与去重。
- 失败页新增 Failure Cluster → `POST /internal/v1/failures/{id}/skill` → `/skills/{skill_id}` 桥接；服务端再次检查 5 个独立 evidence、只传递 taxonomy/cluster、结果保持 `PENDING_REVIEW`。
- 自动评测无真人在线时，评测页仍展示 Hard Gate/Judge/Release Gate 结果，但真人审批节点保持“待审批”；Skill 候选保持 `PENDING_REVIEW`，不能被 Active/Canary 检索命中，超出截止时间后由生命周期投影为 `EXPIRED`。该边界由 Skill 生命周期单测、API 认证/幂等测试和 PostgreSQL contract 覆盖。

## 限制

- Live Model、Live RAG、真实 Shadow/Canary 流量和 7 天线上基线仍未执行；本证据不能替代线上能力证明。
- `56 skipped` 主要来自未配置 `DATABASE_TEST_URL` 的本地全量收集，以及 Live Model/Recovery 条件测试；PostgreSQL contract 已在隔离数据库中实际运行。
