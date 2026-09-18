# Phase N7 前端 Agent 流程与发布观测证据

日期：2026-09-18

## 本轮实现

- `/operations` 增加 Current / Candidate 路由、Response Policy、Skill、质量、安全、P95 时延、P95 成本和人工接管率对比表；缺失的线上聚合值保持 `N/A`。
- `/internal/v1/operations/summary` 增加 `version_breakdown`：按当前发布 assignment 聚合请求、完成/失败、Current/Shadow/Canary、P95 端到端时延、Token usage、成功成本、Route、Skill 命中、Safety 命中/阻断和人工接管率；没有独立 Judge 标注时 `quality_score` 保持 `N/A`。
- `/operations` 的版本表同步展示上述字段，并明确 `unassigned` 与 Shadow 观测不等于候选版本真实执行。
- `/operations` 增加发布负责人、阶段、候选流量、观察结束时间和停止/回滚提示，并每 15 秒重新读取运营摘要与发布列表。
- `/releases/:id` 增加实时发布状态面板：Current → Candidate、负责人、最后更新时间、观察窗口、结构化 Gate、停止原因、回滚版本和最近审计事件。
- 发布实时面板每 15 秒刷新；刷新失败保留上次成功快照并显式提示，不把旧数据伪装成实时数据。
- Markdown 发布报告增加逐项 Gate details，展示观测值、阈值/基线和 `PASS`、`STOP` 或 `INCOMPLETE`，可解释质量、安全、时延、成本和人工接管变化。
- 既有对话工作台、Run Trace、评测、失败归因和 Skill 页面继续保留流程图、分支和语义化数据表；原始 Prompt、工具参数、隐藏推理和未授权纠错文本不展示。

## 本地验证

在 `apps/web` 执行：

```text
npm run typecheck: passed
npm run lint: passed
npm test -- --run: 10 passed
npm run build: passed
npm run bundle:check: passed (Apache-2.0, 799320 bytes)
```

后端 `ruff check src tests`、全量 mypy 通过；隔离 PostgreSQL 环境下当前全量 Python 回归为 `435 passed, 2 skipped`，仅显式 Live Model 测试跳过。PostgreSQL contract/recovery 已分别通过 `49 passed` 与 `17 passed`；这证明数据库契约，不等于真实线上流量收益或模型质量。

## 证据边界

- 本地验证证明组件能编译、渲染并读取后端白名单 DTO；不证明已有真实 Shadow/Canary 流量、七天基线、线上自动停止或一分钟内 kill switch。
- Current / Candidate 的线上完整聚合仍依赖后端真实 assignment 和定价数据；后端未提供的值在页面显示 `N/A`。
- 版本表中的 Shadow 行是 assignment/运行观测归属，不代表候选产生了第二份回复或工具调用；只有 `candidate_execution_allowed=true` 且真实运行时注册、Gate 和流量条件同时满足时，才可解释为候选执行。
- 15 秒轮询是前端刷新机制，线上状态传播延迟仍需在部署环境通过真实停止事件测量。
