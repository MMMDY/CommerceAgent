# Phase N7 高危评测真人审批控制面证据

日期：2026-09-18

## 已落地的控制面能力

- `GET /v1/evals/{eval_run_id}/approval` 返回白名单审批投影：是否需要审批、当前状态、来源、是否已有审计记录、审批记录 ID、审批人引用、决定时间和原因 hash。
- `POST /internal/v1/evals/{eval_run_id}/approval` 仅允许 approver 角色，对报告声明 `human_approval.required=true` 的评测执行批准/拒绝；要求确认短语、原因和幂等键。
- 审批决定写入 append-only `audit.audit_events` 的 `evaluation_human_approval` 事件；浏览器和接口均不返回审批原文，只返回单向 hash。
- 已有最终决定的评测不能被第二次覆盖；幂等重放返回同一结构化结果。
- 评测 Dashboard 在 `pending` 时仍保持不可上线边界；审批 API 的存在不会把 `release_gate` 自动改为通过。

## 验证

- `ruff check`、全量 `mypy src` 通过。
- Admin/approver API 边界与未认证行为测试：`15 passed, 3 skipped`；3 个跳过项为未设置 `DATABASE_TEST_URL` 的 PostgreSQL contract。
- 新增 PostgreSQL contract 覆盖审批审计的租户隔离、最新决定投影和原文不泄露；在隔离 PostgreSQL 环境执行时应纳入现有 contract 总数。
- 前端 Vitest `10 passed`，typecheck、lint、production build 通过。

## 尚未完成的证据门禁

- 当前没有真实 approver 对某个高危评测执行并持久化的生产记录，因此计划中“高危边界 case 必须人工批准”仍保持 `[ ]`。
- 当前没有真实线上发布、Canary/Shadow 流量或一分钟传播时延证据；本控制面不替代这些上线门禁。
