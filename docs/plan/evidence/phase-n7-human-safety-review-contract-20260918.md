# Phase N7 人工复核误差指标合同证据

日期：2026-09-18

## 实现

- `src/harness/human_review.py` 新增 `HumanSafetyLabel`、`ReviewThresholds` 和 `reviewed_safety_stats()`。
- 只有 `source=human_review`、带时区的 `reviewed_at`、唯一 case 标签且覆盖全部 long-tail/safety case 时，才计算安全漏判和低风险误拒绝。
- 缺失标签时状态为 `incomplete`，两类错误数/率和 Gate 均保持 `N/A`；没有批准阈值时只能观测，`gate_pass` 保持 `N/A`，Release 模式整体状态为 `incomplete` 且不会通过 Gate。
- `src/harness/runner.py` 与 `src/harness/live_runner.py` 支持显式传入 `--human-safety-labels`、低风险误拒绝阈值和高风险漏判阈值；不传入时不改变既有评测结果。
- Markdown 报告和 `/evals/:id` 前端展示人工复核状态、缺失标签数、错误数/率和 Gate；未提供人工标签时页面明确说明不由 Safety 命中数推断质量。
- Release 模式遇到 long-tail/safety Track 时，`build_report()` 将人工复核 Gate 纳入最终 `release_gate`；缺标签、缺双侧风险覆盖、缺批准阈值或超阈值均 fail-closed。

## 本地验证

```text
PYTHONPATH=. conda run -n commerce pytest -q tests/unit/test_human_review.py tests/harness/test_report.py
13 passed

conda run -n commerce python -m ruff check \
  src/harness/report.py src/harness/human_review.py \
  src/harness/runner.py src/harness/live_runner.py \
  tests/unit/test_human_review.py tests/harness/test_report.py
All checks passed

conda run -n commerce python -m mypy src
Success: no issues found in 145 source files
```

## 边界

本证据只证明指标合同、缺失值语义和本地前端/报告接线；当前环境没有真实线上人工标签、批准阈值或五类 Safety 误差标注，因此 `/operations` 的线上漏判/误拒绝验收项继续保持 `[ ]`，不能据此宣称真实质量率已完成。
