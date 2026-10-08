# Phase N7 七天 SLO 基线冻结器

日期：2026-09-18

## 已实现

- `src/release/slo_baseline.py` 提供 fail-closed 的 `freeze_baseline()`；
- 要求最早到最晚观测时间至少 168 小时、至少 7 个本地日期、同时包含工作日和周末；
- P50/P95/P99 E2E、P95 成本、低风险人工接管率和终态回复覆盖率只从真实提供的数值聚合；任何必需指标缺失或不足最小样本数时直接拒绝冻结；
- 时间戳必须带时区，时延/成本不可为负，比例字段必须在 `[0, 1]`；
- `scripts/build_slo_baseline.py` 支持 JSON 数组或 JSONL 脱敏样本，输出冻结 baseline JSON；
- `tests/unit/test_slo_baseline.py` 覆盖工作日/周末窗口、短窗口、缺失指标、无时区时间和非法比例。

## 验证

```text
conda run -n commerce pytest -q tests/unit/test_slo_baseline.py
3 passed

conda run -n commerce python -m ruff check src/release/slo_baseline.py tests/unit/test_slo_baseline.py scripts/build_slo_baseline.py
All checks passed

conda run -n commerce python -m mypy src/release/slo_baseline.py
Success: no issues found in 1 source file
```

## 尚未勾选的验收项

代码只提供冻结前置校验，当前工作区没有真实覆盖工作日和周末的七天生产 Shadow 数据，因此“7 天基线覆盖工作日和周末后冻结绝对 SLO”及“冻结后写回运维手册”仍保持 `[ ]`。本地 fixture 不作为生产基线证据。
