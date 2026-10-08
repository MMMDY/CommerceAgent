# Phase N7 前端流程状态与审批边界证据

日期：2026-09-18

## 已落地

- `RunInsight` 将 Run 主可视化与事件链、RAG 证据接口解耦：事件链或证据接口失败时仍展示已取得的决策链、编排拓扑、时延、模型调用和工具调用，并使用 `partial` 状态说明缺失原因。
- Run 主接口返回 `403` 时使用 `forbidden` 状态；不会将无权限或接口失败渲染成“暂无证据”或绿色成功。
- 评测 Dashboard DTO 新增白名单 `human_approval` 投影。评测页将 `pending` 显示为“真人审批待完成”，并明确当前状态、来源、线上命中限制和超时处置；`release_gate` 不再被视觉上误认为人工授权。
- 对话页在 SSE 断流时显示“断流 · 轮询回退”，保留轮询同步的 Run、事件和消息状态。
- 运营页主聚合接口的 403 使用 `forbidden`，Safety 审计、失败学习和发布状态等次级接口失败时保留主聚合并显示部分状态；失败列表在样本与聚合接口只有一方成功时也不会整页伪装为完整。

## 证据

- 后端：`tests/harness/test_dashboard.py`，新增审批状态投影测试；目标测试集 `16 passed`（`tests/harness/test_dashboard.py tests/harness/test_runner.py`）。全量回归当前为 `406 passed, 63 skipped`，跳过项均为本环境未提供的 PostgreSQL/live 条件。
- 前端：`npm test -- --run`：`16 passed`；`npm run typecheck`、`npm run lint`、`npm run build` 和 bundle/license 检查通过（825564 bytes，Apache-2.0）。
- 后续状态投影补强：失败详情的操作失败保留最近成功快照并显示 `partial/forbidden`；Skill Registry 将列表接口和 kill-switch 接口分别显示错误；Eval、Run、运营、Skill 和 Release 状态使用统一中性/成功/警告/失败标签。
- 本轮继续补强：对话 SSE 纳入人工接管、提交/校验、RAG 失败和回复发布失败事件；运营次级接口分别显示 loading、403、partial 和最近成功快照，不把未返回的空数组解释为无数据。
- 构建仍有 Vite 大 chunk warning，但没有扩大 bundle 上限；既有 bundle/license 检查策略保持不变。

## 边界

- 本证据只证明本地代码、白名单投影和页面状态行为，不证明真实真人审批记录、真实线上流量、线上传播时延或生产 Canary 已完成。
- 事件链与 RAG 证据接口部分失败时，页面只保留成功取得的聚合数据；缺失字段继续显示 `N/A`，不会由浏览器自行推断。
