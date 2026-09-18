# Phase N5 运营流程可视化与下钻证据

## 已实现

- `/internal/v1/operations/summary` 支持 `window_hours`、授权范围内的 `tenant_id`、`route` 和 `model` 查询参数。
- 运营聚合指标、小时趋势、安全统计、模型成本拆分和最近 Run 列表共享同一筛选范围。
- 最近 Run 只返回 `run_id`、状态、route/workflow、模型标识、端到端时延和成本等脱敏字段；页面可进入 `/runs/:id` 查看决策链、事件路径、时延瀑布、工具元数据和授权 RAG 证据。
- tenant 选择器当前只显示 `demo-tenant`；服务端拒绝其他 tenant，避免将查询参数误当作跨租户授权。
- 运营页继续保留语义化表格，图表聚合值与表格同源，缺失成本/时延保持 `N/A`。

## 验证

```text
ruff check src/repositories/run_observability.py apps/api/main.py: passed
frontend typecheck: passed
frontend build: passed
frontend bundle:check: passed (Apache-2.0, 796109 bytes)
tests/harness/test_dashboard.py: 4 passed
full Python regression: 367 passed, 56 skipped (live model/PostgreSQL-only tests outside the default environment)
PostgreSQL contract suite: 45 passed
PostgreSQL smoke: `operations_summary(tenant_id="missing-tenant", route="readonly", model="provider/model")` returned `0` without SQL error
```

## 边界

契约环境已验证新增查询在 PostgreSQL 上可执行；当前 smoke 使用空租户，仍需在有真实脱敏 Run 的环境验证 route/model 聚合数值对账。本地前端不会用 fixture 伪造线上 Run、跨 tenant 数据或真人审批状态。
