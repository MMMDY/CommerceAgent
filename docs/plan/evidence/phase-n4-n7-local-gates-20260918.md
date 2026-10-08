# Phase N4/N5/N6/N7 本地安全与发布边界证据

## 已实现

- Release Check 读取独立 safety report；任意 `p0_failure_count > 0` 都返回 `p0_safety_failures` 并阻断发布。
- `AttributionCategory` 的 8 个一级类别（intent/policy/tool/retrieval/safety/model/response/unknown）均有确定性正例和不应归入该类的负例。
- Skill Registry 通过 `select_skill_from_registry()` 隔离数据库读取异常；异常只产生 registry miss，普通路由继续执行，Safety Router 不受影响。
- Progressive Delivery 的稳定桶按 tenant、actor、conversation 纳入 hash；run 仅作为审计/持久化 assignment 身份，不影响桶位，因此同一会话不会因新建 Run 发生版本跳变，浏览器不接触原始身份。
- `scripts/check_canary.py --markdown-report` 生成脱敏的 Current/Candidate 观察报告，包含自动停止状态、触发原因、Route/Policy/Skill、质量/安全以及 P95 时延/成本 delta；缺失数据保持 `N/A`。
- deterministic `safety_zh` 五条高危 case 通过真实 AgentLoop hard gate，输出 `Hard 通过 5/5`、`P0 hard fail 0`；评测报告仍为 `incomplete`，因为 Judge 未启用，不能当作高危线上能力或真人批准证据。

## 验证

```text
tests/deployment/test_phase6_ops.py + safety/report tests: 18 passed
tests/unit/test_failure_taxonomy.py + failure attribution/signals: 22 passed
tests/unit/test_skill_retriever.py: 6 passed
tests/unit/test_progressive_delivery.py: 5 passed
tests/unit/test_check_canary.py + canary/release transition tests: 8 passed
tests/harness/test_deterministic_runtime.py: 6 passed
synthetic safety hard gate: 5/5 hard passed, P0 hard fail 0
ruff: passed
mypy: passed
```

## 边界

这些证据验证的是 fail-closed 代码边界和确定性分桶，不等同于真实线上安全漏判率、真实 Canary 流量收益、1 分钟线上 kill switch 或 7 天 SLO 基线；相关计划项继续保持未勾选。
