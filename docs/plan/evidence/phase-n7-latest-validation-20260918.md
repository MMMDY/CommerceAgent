# Phase N7 当前工作区验证记录

日期：2026-09-19（沿用文件名以保留既有引用）

## 本地可复现验证

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| Python 回归（无 DB 条件） | `PYTHONPATH=. conda run -n commerce pytest -q` | `406 passed, 63 skipped` |
| Python 全量回归（隔离 PostgreSQL head `20260918_0025`） | `DATABASE_TEST_URL=temporary ... pytest -q` | `459 passed, 2 skipped`；contract/recovery 不跳过 |
| Python lint | `conda run -n commerce python -m ruff check src tests` | 通过 |
| Python 类型 | `conda run -n commerce python -m mypy src apps/api/main.py` | 通过，146 source files |
| 前端类型 | `npm run typecheck` | 通过 |
| 前端 lint | `npm run lint` | 通过 |
| 前端测试 | `npm test -- --run` | 8 files / 24 tests passed |
| 前端构建 | `npm run build` | 通过；Vite 仅提示 chunk 大于 500 kB |
| Bundle/license | `npm run bundle:check` | 通过；Apache-2.0；JavaScript 851794 bytes |

## 未宣称完成的外部证据

- demo 数据库已正式迁移到 `20260918_0025`，最新 app 镜像已通过 `/health/ready`；一次性隔离数据库上的 PostgreSQL contract/recovery 与全量 Python 回归通过。详细过程见 `docs/plan/evidence/phase-n7-isolated-postgres-validation-20260919.md` 与 `docs/plan/evidence/phase-n7-demo-runtime-validation-20260919.md`。
- live model 测试因未显式设置 `RUN_LIVE_MODEL_TEST=1` 而跳过；
- 真人审批、真实 5% → 25% → 50% → 100% Canary、生产传播时延和 7 天工作日/周末基线没有本地替代证据，计划中的对应 checkbox 保持 `[ ]`；
- 人工复核误差指标已具备 fail-closed 合同，但本地没有真实人工标签和批准阈值；安全漏判/低风险误拒绝仍显示 `N/A`，不能当作线上质量率。
- 严格执行 `ruff check src tests scripts` 仍包含仓库历史脚本格式问题，本轮只将 `src tests` 结果记为通过。

## 前端展示范围

对话、Run、评测、运营、失败、Skill 和 Release 页面均有结构化流程投影；页面只展示白名单决策、状态、指标、事件和脱敏证据，不展示 Prompt、思维链、工具参数、密钥或未授权纠错文本。统一 `StatusTag` 覆盖 Run、模型/工具调用、阶段时延、运营 Run、Skill 和 Release 状态；未知状态使用中性状态标签，不显示为成功。对话页可视化受理 → Safety → Domain → Intent → Policy → Agent → Guardrail → 回复，并展示 RAG、Tool、Skill、兜底分支；Run/评测/运营/失败学习/发布页提供对应流程和 ID 下钻。

历史评测产物维护：使用现有 `write_report()` 对 18 个缺少新聚合字段的 `report.json` 进行兼容回填并重新生成 Markdown；没有 usage/价格的数据保持 `N/A`，没有新增虚构分数。以 `release-20260916-bounded-judge-v2` 为例，Markdown 现包含 Judge 各 rubric 平均分、加权总分、时延/Token/成本表和明确的 `N/A`。

本轮前端增量将后端 `EventType` 已定义的 `handoff_created`、`mutation_prepared`、`commit_started`、`state_verified`、`mutation_uncertain` 和 `terminal_response_publish_failed` 纳入对话页 SSE 订阅及时间轴标签，并保留 RAG 失败等流程投影事件的兼容展示；运营页对次级审计、失败学习和发布接口区分 loading、403、partial、刷新失败和最近成功快照；Run/Release 页面补齐已有事件和 assignment comparison 的 Skill/Release 下钻，Run 详情新增服务端明确关系的评测/失败下钻，Skill 详情可按 cluster_key 服务端过滤失败样本和聚合趋势。对话页 Agent Flow 进一步在受理、路由、执行、Guardrail 和回复节点展示真实事件数/可测时延，终态节点（包括受理）没有对应事件证据时不显示为完成；`/skills/:id` 增加失败簇→Gate→Paired Eval→真人审批→Release 生命周期状态链路，未知/失败审批状态保持中性或阻断语义，Skill Release 关联次级接口补齐 loading/empty/error/403，缺失时间戳或评测/发布关联保持 `N/A`/待处理；评测页新增 Markdown 报告下载，历史命名报告可正常下钻；运营页新增 Safety Triaged/Blocked/Handoff 趋势图和各高危类别命中/人工接管柱状图，构建后的 JavaScript 为 851794 bytes，当前 demo 入口为 `index-VUuGCcEu.js`，未改变 bundle/license 门禁。详细边界见 `docs/plan/evidence/phase-n7-frontend-flow-timing-20260919.md`、`docs/plan/evidence/phase-n7-frontend-skill-lifecycle-flow-20260919.md`、`docs/plan/evidence/phase-n7-safety-trend-visualization-20260919.md` 和 `docs/plan/evidence/phase-n7-frontend-state-coverage-audit-20260919.md`。
