# Phase N3 长尾评测与发布 Gate 证据

日期：2026-09-18

## 长尾 deterministic hard gate

命令：

```bash
PYTHONPATH=. python -m src.harness.runner \
  --dataset evals/long_tail_zh/cases.jsonl \
  --judge off \
  --output-dir evals/reports/long-tail-hard-gate-20260918
```

结果：

- `runtime=deterministic_fixture`，来源为独立 `code_owned_factory`；
- 6 个低风险长尾 case 全部完成，Hard Gate `6/6`；
- 业务工具调用 `0`，转人工 `0`，评测 Runtime 转人工率 `0.0000`；
- 报告状态为 `incomplete`，因为 Judge 未启用；这不是线上误拒绝率，也不是真人批准或真实模型能力证明。

## 发布 Gate

- `CanaryMetrics` 新增 `quality_gate_pass`、`safety_gate_pass`；任一缺失或失败都 fail closed；
- Markdown 发布报告逐项展示 Quality/Safety Gate 的 `PASS`、`STOP` 或 `INCOMPLETE`；
- 既有 P0、安全覆盖率、P95/P99 时延、P95 成本、低风险接管、Skill scope 和目标 slice Gate 保持不变。

## 验证

- 相关 Ruff、mypy 通过；
- 长尾 Runner/报告测试、Canary/调度器/发布报告测试通过；
- PostgreSQL 和真实模型环境未配置，线上 RAG、真实 Canary 流量和 7 天基线仍不宣称完成。

## 无真人审批时的自动评测边界

高危数据集的 manifest 可声明 `requires_human_approval_before_release=true`。本地 Runner
会将该批次写为 `human_approval.status=pending`，强制 `release_gate=false`，并将报告标记为
`status=incomplete`；这只能证明系统 fail closed，不能证明已有人工批准。

因此，在自动评测环境没有真人 approver 记录时：

- 评测仍可生成 Hard Gate、Judge 和资源统计，供后续复核；
- Skill 候选保持 `PENDING_REVIEW`，不会进入 Active/Canary，也不会被线上 Skill 检索命中；
- 到达 `review_deadline` 后只允许投影为 `EXPIRED`，不能用自动化结果替代真人审批；
- 当前项目没有提供真实 approver、审批时间和审批审计事件，所以本阶段“高危边界 case 必须人工批准”仍保持未完成。
