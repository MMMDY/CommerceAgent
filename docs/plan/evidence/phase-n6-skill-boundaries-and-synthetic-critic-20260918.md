# Phase N6 Skill 边界与 Synthetic Critic 证据

## 已实现

- Skill 检索同时校验 `tenant_id` 和 tenant scope value；route scope 必须匹配当前受控 route。
- Skill strategy 只投影 `response_policy`、`allowed_decisions`、`forbidden_tools`、`ttl_seconds` 白名单，不能通过候选字段扩大工具、route 或 Prompt 能力。
- 积极情绪 Skill 的目标样本与退款/高危反例有独立检索回归；`PENDING_REVIEW` 候选不会命中 active 检索。
- 新增独立 `src/synthesis/critic.py`，对合成样本检查标签/风险一致性、自然长度、模板占位符和安全工具边界；`validate_candidates()` 在候选进入评测前强制执行。
- Judge 配置生成 secret-free `judge_config_hash`；评测报告同时记录 Generator/Judge 标识，Release Check 拒绝二者配置标识相同。
- Canary 门禁新增 Skill 跨 scope 命中和目标 slice 质量下降的 fail-closed 停止信号。

## 验证

```text
tests/unit/test_skill_retriever.py: 5 passed
tests/harness/test_synthetic_data.py: passed
tests/unit/test_canary_guard.py: 3 passed
tests/deployment/test_phase6_ops.py: passed
tests/harness/test_judge.py: passed
ruff: passed
mypy: passed (140 source files)
```

## 仍未声称完成

高危边界样本的真人批准、真实线上 kill switch 一分钟内生效、真实 Shadow/Canary 流量和线上质量收益仍需要外部证据，当前保持计划中的 `[ ]`。
