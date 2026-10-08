# Phase N7 跨资源下钻关系投影证据

日期：2026-09-18

## 本轮实现

- 新增 `GET /v1/runs/{run_id}/relations`，先按 tenant/actor 校验 Run 所属，再返回明确关联的失败记录和评测 `eval_run_id + case_id + attempt_no`；浏览器不再根据页面结果猜测关系。
- 评测 Case 详情返回 `failure_ids`，因此 Case → Run Trace / Failure 均有明确后端 ID。
- 失败查询支持 `run_id`、`eval_run_id`、`case_id` 组合过滤；Skill/Release 关系读取也保持不可变 ID 和 tenant 边界。
- Run 详情新增评测 Case、失败样本入口；缺少关系时显示 `N/A`，关系接口失败时保留其它 Run 证据并显示 partial 状态。
- Skill 详情读取明确的 assignment 关系并提供 Release 入口；Release 详情已有 Run/Skill 入口，用户可沿 Run 关系继续到评测和失败。
- 关系投影只包含 ID、Track、Attempt 和通过状态等白名单元数据，不返回 Prompt、原始回复、工具参数或思维链。
- 新增 `tests/harness/test_report_dashboard_consistency.py`：对同一份 report JSON 同时生成 Dashboard DTO 和 Markdown，校验 counts、通过率、Track、各 rubric 平均分、加权分、时延/成本分布和 Safety 指标一致；前端展示仍只消费服务端 Dashboard DTO，不自行重算 Gate。

## 验证

```text
PYTHONPATH=. conda run -n commerce pytest -q tests/unit/test_failure_repository_filter.py tests/unit/test_eval_relations.py
4 passed

conda run -n commerce python -m ruff check \
  src/repositories/failures.py src/repositories/skills.py \
  src/repositories/releases.py apps/api/main.py \
  tests/unit/test_failure_repository_filter.py tests/unit/test_eval_relations.py
All checks passed

conda run -n commerce python -m mypy src apps/api/main.py
Success: no issues found in 146 source files

JavaScript bundle/license check: 825564 bytes，Apache-2.0

npm --prefix apps/web run typecheck && npm --prefix apps/web run lint
通过

PYTHONPATH=. conda run -n commerce pytest -q tests/harness/test_report_dashboard_consistency.py
1 passed

PYTHONPATH=. conda run -n commerce pytest -q
406 passed, 63 skipped
```

## 边界

- 旧评测报告没有 `actual.run_id` 时不会生成虚假 Run 链接。
- 旧报告、无 durable ID 或无 assignment 审计时继续显示 `N/A`，不会猜测关联。
- 2026-09-19 已在当前 head `20260918_0025` 的隔离 PostgreSQL 合同和 demo runtime 上复核关系投影、Dashboard/Markdown 同源聚合与前端入口；因此计划中的实现项已标记完成。
- 真实线上流量传播、质量收益和生产数据分布仍不由本证据替代，继续由 Canary、SLO、传播和线上 Gate 的独立 `[ ]` 项约束。
