# Phase N7 历史评测报告下钻验证

日期：2026-09-19

## 问题

`/v1/evals` 会列出既有命名报告目录（例如 `baseline-20260918`），但详情路径此前只接受 UUID，导致列表中的历史评测点击后返回 404。

## 修复

- `_eval_report_paths()` 现在接受 UUID 和受限 basename（字母、数字、`.`、`_`、`-`，最长 128），仍拒绝路径穿越和绝对路径。
- 命名历史报告可读取 Dashboard、Case 和审批状态。
- 历史命名报告没有 durable UUID 时仍可展示；Case → Failure 关系保持空集合，不伪造数据库关联。

## 验证

```text
tests/unit/test_eval_report_paths.py: 6 passed
GET /health/ready: 200 {"status":"ready"}
GET /v1/evals/baseline-20260918/dashboard: 200
GET /v1/evals/baseline-20260918/cases?limit=1: 200
GET /v1/evals/baseline-20260918/approval: 200
```

## 安全边界

`../secrets`、`/tmp/report`、空 ID、含 `/` 的 ID 和超过长度限制的 ID 均返回 404；报告内容仍经过现有脱敏/白名单投影。
