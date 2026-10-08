# Phase N7 Safety 趋势可视化证据

日期：2026-09-19

## 实现

- `/operations` 新增 Safety 趋势折线图，展示后端按小时聚合的 Triaged、Blocked、Handoff；新增高危类别命中/人工接管柱状图。
- 图表和语义化数据表使用同一个 `safety_trend` / `safety_category_breakdown` DTO；图表不在浏览器端重新推断指标。
- 漏判/误拒绝依赖独立真人标签，当前只在 DTO 提供完整复核结果时显示，否则保持 `N/A`。
- ECharts 使用 Apache-2.0 依赖，沿用现有 bundle/license 门禁。

## 验证

```text
npm run typecheck: passed
npm run lint: passed
npm test -- --run: 8 files / 24 tests passed
npm run build: passed
npm run bundle:check: passed (Apache-2.0, 851794 bytes)
```

Demo `/internal/v1/operations/summary` 已返回五类 `safety_category_breakdown`（`account_takeover`、`transaction_bypass`、`privacy`、`prompt_injection`、`unknown_tool_state`）；当前 `false_negative_count` / `false_rejection_count` 为 `null`，页面保持 `N/A`。

## 边界

图表只证明聚合数据的可视化，不证明漏判/误拒绝率；后两项仍需真人标签和批准阈值，不能用 Safety 命中数或图表趋势替代。
