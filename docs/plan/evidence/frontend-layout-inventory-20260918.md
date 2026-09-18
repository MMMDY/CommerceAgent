# 前端流程可视化与响应式组件清单

日期：2026-09-18

## 页面与流程证据

| 页面 | 主流程/图表 | 关键下钻 | 窄屏策略 |
|---|---|---|---|
| 对话工作台 | 受理 → Safety → Domain → Intent → Policy → Agent → Guardrail → 回复；RAG/工具/Skill/兜底分支 | Run Trace、事件、RAG 证据 | 侧栏变抽屉，流程节点纵向排列 |
| `/runs/:id` | 决策链、事件路径、时延瀑布、模型调用/工具表 | 脱敏事件与证据 | 表格横向滚动，事实卡单列 |
| `/evals` | Hard Gate → Judge → Release Gate → 真人审批；质量漏斗、rubric 热力图、分数分布 | Case → Attempt → Trace | 指标网格单列，筛选控件全宽 |
| `/operations` | 线上 Agent 阶段、Safety 态势、RAG/模型/工具/失败学习分支；Current/Candidate 路由、策略、Skill 与成本/时延对比 | 失败归因、Run Trace、发布详情 | 分支卡片两列/单列，版本对比表横向滚动 |
| `/failures` | 采集 → 聚类 → 归因 → 人工复核；Top-N、taxonomy、趋势 | Failure → Trace | 趋势表横向滚动 |
| `/skills` | Candidate → Pending Review → Approved → Canary → Active 等状态漏斗 | Skill 版本与 paired evaluation | 审批按钮和门禁信息保留在窄屏 |
| `/releases/:id` | Shadow → 5% → 25% → 50% → 100%；流量进度、负责人、Gate、Current/Candidate 决策差异、停止/回滚审计；15 秒实时状态刷新 | assignment → Run、审计事件 | 阶段卡片纵向排列，对比表横向滚动 |

## 统一状态合同

`PageState` 统一渲染 `loading / empty / partial / error / forbidden`。`error`、`forbidden` 使用红色警示，`partial` 使用黄色关注色，未知值使用 `N/A`，不会映射为绿色成功。

共享 formatter 位于 `apps/web/src/ui/formatters.ts`，统一处理时间、毫秒、token、微 USD 和缺失值。复杂数据同时提供可读图形和语义化表格。

## 验证

在 `apps/web` 执行：

```bash
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

当前结果：全部通过，Vitest `7 passed`；N7 前端发布观测证据见 `phase-n7-frontend-flow-observability-20260918.md`。
