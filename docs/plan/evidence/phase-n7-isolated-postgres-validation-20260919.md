# Phase N7 隔离 PostgreSQL 与全量回归证据

日期：2026-09-19

## 验证方式

- 本记录最初发现 demo 数据库停在 `20260917_0018`；后续已通过正式 migration 流程将 demo 数据库迁移到 `20260918_0025`。本文件中的回归结果仍指一次性隔离数据库，demo runtime 验证另见 `phase-n7-demo-runtime-validation-20260919.md`。
- 创建唯一临时数据库，以当前 migration chain 迁移到 `20260918_0025`。
- 在该临时库上执行完整 Python 套件；测试结束后自动 `DROP DATABASE` 清理临时库。
- migration head、数据库 URL 和临时库名称未写入报告或提交文件，密码未进入输出。

## 结果

```text
当前 head：20260918_0025
PYTHONPATH=. conda run -n commerce pytest -q
459 passed, 2 skipped, 87 warnings
```

两个跳过项均为明确要求 `RUN_LIVE_MODEL_TEST=1` 的外部模型 integration；PostgreSQL contract/recovery 不再跳过。单独的 `tests/contract tests/recovery` 结果为 `69 passed`。

## 边界

- 这是隔离数据库上的 schema、repository、recovery 和 API 合同验证，不是生产数据一致性、真实人工审批或线上流量证据。
- 本记录生成时 demo 数据库尚未迁移；后续迁移和最新镜像 readiness 已单独记录，避免将隔离回归结果与 demo runtime 证据混为一谈。
