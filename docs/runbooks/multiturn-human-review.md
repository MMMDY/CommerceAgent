# Multi-turn 人工复核操作手册

这项复核用于确认 User Simulator 没有泄露 gold response，且每条用户动作符合场景约束。它必须由独立 reviewer 完成；deterministic Runner、Judge 或开发者推断不能替代人工标签。

## 1. 获取脱敏队列

队列由报告生成，默认抽样 20 条，并按 scenario family 稳定轮询，优先保留多轮轨迹：

```bash
PYTHONPATH=/home/CommerceAgent conda run -n commerce \
  python /home/CommerceAgent/scripts/build_multiturn_review_queue.py \
  --report /home/CommerceAgent/artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/multiturn-report.json \
  --output /home/CommerceAgent/artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/human-review-queue.json \
  --sample-size 20
```

当前待复核队列已经生成，reviewer 直接读取：

`/home/CommerceAgent/artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/human-review-queue.json`

Reviewer 只读取 `items[].scenario_id`、`items[].turns` 和可见的 `review` 字段。队列不包含 target intent、reference solution、Verifier 状态或 Judge 结果；若发现此类字段，应停止复核并重新生成队列。

## 2. 写入标签

标签文件为 JSONL，每行对应一个且仅一个队列 scenario。字段合同如下：

```json
{
  "scenario_id": "pilot_order_001_v1",
  "source": "human_review",
  "reviewer_id": "reviewer-001",
  "reviewed_at": "2026-09-21T12:00:00+08:00",
  "rubric_version": "multiturn-human-review-v1",
  "gold_response_leakage": "none",
  "semantic_fidelity": "pass",
  "simulator_action_validity": "pass",
  "notes": "说明观察到的用户动作和回复是否符合可见对话上下文。",
  "label_hash": "sha256:<independent-label-content-hash>"
}
```

`gold_response_leakage` 可取 `none`、`suspected`、`confirmed`；其它两个判断可取 `pass`、`fail`、`unclear`。`reviewer_id`、`reviewed_at`、`rubric_version`、`notes` 和 `label_hash` 均不能为空。不要把队列中的 gold、隐藏标签或 Judge 结论写入 notes。

## 3. 严格校验

```bash
PYTHONPATH=/home/CommerceAgent conda run -n commerce \
  python /home/CommerceAgent/scripts/validate_multiturn_review.py \
  --queue /home/CommerceAgent/artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/human-review-queue.json \
  --labels /home/CommerceAgent/artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/human-review-labels.jsonl \
  --output /home/CommerceAgent/artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/human-review-stats.json
```

只有命令退出码为 `0` 且 stats 的 `status=complete`、`reviewed_count=20` 时，人工复核证据才完整。缺少标签、重复 scenario、越界标签或缺失元数据会保持 `incomplete`。`unclear` 是合法的人工结论，但会使 `gate_pass=false`；任何非通过结论都不能填充为通过。

API 和前端只展示聚合状态，不展示 reviewer notes、标签路径或隐藏评测字段。完成校验后应保留 queue、labels 和 stats 的审计关联，并在评测证据文档中记录 reviewer 与 rubric 版本。

## 4. 计划级门禁

人工标签校验通过后，再运行计划级审计，确认它与静态基线证据一起满足完成定义：

```bash
PYTHONPATH=/home/CommerceAgent conda run -n commerce \
  python /home/CommerceAgent/scripts/audit_layered_evaluation.py \
  --human-review-stats /home/CommerceAgent/artifacts/evals/multiturn_pilot_judge_20260921/human-review-stats.json \
  --baseline-comparison /home/CommerceAgent/artifacts/evals/static-baseline-judge-repro-v3-20260921/comparison.json \
  --output /home/CommerceAgent/artifacts/evals/static-baseline-judge-repro-v3-20260921/layered-evidence-audit.json
```

只有输出 `status=complete` 且退出码为 `0` 才能更新计划完成状态。当前缺少 reviewer 标签或同签名 Judge-dependent 基线时，命令返回 `status=incomplete` 和退出码 `2`。

如果项目负责人明确决定跳过人工复核，只能使用显式豁免参数记录自动化审计；这不会生成或伪造人工 labels，也不会把 `release_gate` 改为通过：

```bash
PYTHONPATH=/home/CommerceAgent conda run -n commerce \
  python /home/CommerceAgent/scripts/audit_layered_evaluation.py \
  --human-review-stats /home/CommerceAgent/artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/human-review-stats.json \
  --baseline-comparison /home/CommerceAgent/artifacts/evals/static-baseline-judge-repro-v3-20260921/comparison.json \
  --output /home/CommerceAgent/artifacts/evals/static-baseline-judge-repro-v3-20260921/layered-evidence-audit-automated-only.json \
  --skip-human-review \
  --waiver-reason "项目负责人明确要求跳过本轮人工复核"
```

该模式的 `human_review_policy.status` 为 `waived`，`automated_gate` 只反映剩余自动化证据；原计划的人工复核完成状态仍不是 `complete`。
