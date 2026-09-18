# Phase N7 前端 Agent 生命周期可视化证据

日期：2026-09-18

## 本轮实现

- 控制面页面统一展示两条泳道：
  - 在线请求链路：受理 → Safety / Intent → Policy Router → Agent 编排（RAG、Tool、Skill）→ Guardrail → 回复发布。
  - 质量与学习链路：评测 → 失败归因 → 经验 Skill → Shadow / Canary 发布。
- `/failures` 样本表增加脱敏 Run 下钻；失败详情增加 Run Trace 链接、Trace event 引用标签、失败池和 Skill Registry 入口。
- 失败 DTO 中已有的 `eval_run_id + case_id` 现在展示为真实评测批次入口，并通过 `case_id` 自动打开 Case Trace 下钻。
- 评测 Case 的运行时 Run ID 贯通 `RuntimeTrace → report.actual → Case DTO → /runs/:id`；旧报告或没有持久化 Run 的 Case 保持 `N/A`。
- 对话页 Agent Flow 区分 RAG 的三种状态：未使用 / 无检索事件、已尝试检索但最终未引用、存在最终引用证据；检索失败单独显示失败状态。
- 当前控制面页面在生命周期图中高亮，评测、失败、Skill、Release 节点提供资源入口。
- Release 列表和详情补齐真实 loading、403/error PageState，以及未知发布阶段的 `partial` 提示；未知阶段不会被推断为可扩流。
- 状态投影补强：Run/Release 详情使用统一 `StatusTag`，`ACTIVE/completed` 才显示成功色，待审批/观测显示警示色，失败/回滚显示危险色，未知后端状态保持中性；避免未知值被误读为成功。

## 验证

在 `apps/web` 执行：

```text
npm run typecheck       通过
npm run lint            通过
npm test -- --run       5 files / 13 tests passed
npm run build           通过
npm run bundle:check    passed；Apache-2.0；JavaScript 816078 bytes
```

Python 定向验证：

```text
PYTHONPATH=. conda run -n commerce pytest -q tests/harness/test_dashboard.py tests/harness/test_runtime_adapter.py tests/harness/test_run_driver.py tests/harness/test_report.py
17 passed
```

## 限制

- 评测 Case 只有在服务端返回真实 `run_id` 时才能下钻到 Run Trace；没有该字段的旧报告不会生成虚假 Run 链接。
- Skill 详情和 Release 详情的关联仍以服务端返回的不可变 ID / assignment 为准；没有明确关联时保持 N/A。
- 本地构建和测试不能证明真实线上流量、审批记录或跨页面数据在生产环境已经完整传播，因此计划中的“全页面互相下钻且数值与 Markdown 完全一致”继续保持未完成。
