# Phase N2 Domain/Risk 独立置信度证据

## 已实现

- `IntentClassification` 支持独立的 `domain_confidence` 和 `risk_confidence`，兼容旧 Provider 时才回退到整体 `confidence`。
- `src/orchestration/confidence.py` 提供版本化、单调、保守的 Domain/Risk 分别校准；未知 Domain 或未知 Risk 的可用置信度固定为 `0`。
- 对 conversational route，Domain 低置信度进入 `ask_user`，Risk 低置信度进入 `human_handoff`；不再用一个总分同时代表两个安全维度。
- routing 事件、Run Trace 和 Agent Flow 展示 Domain/Risk 校准分数及 `confidence_calibration_version`，仍只返回白名单结构化字段。

## 验证

```text
tests/unit/test_confidence_calibration.py: 3 passed
tests/unit/test_route_decision.py + test_intent_classifier.py + test_risk_router.py + test_run_insight.py: 26 passed
Python full regression: 367 passed, 56 skipped
ruff: passed
mypy: passed
frontend lint/typecheck: passed
frontend Vitest: 7 passed
frontend build/bundle:check: passed
```

## 边界

当前 profile 是代码拥有的保守策略校准 profile，不把 deterministic 或本地测试结果解释为真实模型可靠性；后续若有人工标注校准集，可在保持版本和审计字段不变的前提下替换为离线拟合 profile。Live Model、线上误拒绝率和真实安全漏判仍保持计划中的独立门禁。
