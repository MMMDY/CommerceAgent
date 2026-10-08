# Phase N7 Shadow Assignment 与 Candidate 对比证据

日期：2026-09-18

## 实现

- Router Shadow 只生成结构化 `RouteDecision` 和 `routing_shadow_compared` 事件，不进入 Agent Loop，不调用业务工具，也不发布第二份回复。
- Skill Shadow 只记录白名单匹配和 match score；`execute_readonly_run` 不把 Shadow strategy 注入执行 Prompt。
- Shadow assignment 固定选择 Current，`candidate_execution_allowed=false`；写风险请求即使进入 Shadow 观察，也不会把 Candidate 送入 prepare/commit。
- assignment comparison 记录 Current/Candidate route、response policy、Skill 和成本差值；未知成本显式为 `null`。Skill 检索完成后通过幂等 assignment 更新补全 Candidate Skill，不创建重复 assignment。
- migration `20260918_0025` 只授予 runtime 更新 `release_assignments.comparison_json` 的列级权限。

## 验证

```text
tests/unit/test_route_decision.py                 PASS
tests/unit/test_progressive_delivery.py           PASS
tests/contract/test_release_assignment_repository.py 1 passed
tests/contract/ 全量                               49 passed
ruff check src tests / mypy src                    PASS
```

## 边界

这些测试证明 Shadow/Candidate 的本地执行边界和 PostgreSQL assignment 持久化契约；
没有把它们当作真实 Shadow/Canary 流量、7 天基线或线上传播时延证据。
