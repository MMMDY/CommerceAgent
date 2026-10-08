# User Simulator 与分层评测实施证据

日期：2026-09-22

## 已实现

- `src/harness/multiturn_schema.py`：`ScenarioSpec`、`UserAction`、逐轮 Trace、Feedback 和双侧报告合同。
- `src/harness/user_simulator.py`：结构化动作解析、事实边界、隐藏答案泄露检查、`resist`/`abandon`/`finish` 和独立 Simulator 配置元数据。
- `src/harness/intent_state.py`：`NOT_RAISED → RAISED → ADDRESSED → VERIFIED`，拒绝未提出意图直接完成。
- `src/harness/multiturn_runner.py` / `multiturn_verifier.py` / `multiturn_report.py`：max turns、取消、超时、重复动作、simulator-side 与 agent-side 分母和结构化反馈。
- `src/harness/seed_profile_generator.py`：种子脱敏、Profile 生成、语义锚点保持、`seed_id → profile_id → scenario_id` 追溯和 CLI。
- `src/harness/catalog_schema.py` / `catalog_loader.py` / `catalog_evaluator.py` / `catalog_report.py` / `catalog_runner.py`：500 商品、100 问题、99 选择题、1 安全题、规格证据回指、独立 Catalog Track 和 300 个商品多轮 Profile 场景骨架。
- `src/harness/report.py` / `dashboard.py`：Hard Dimension、failure reason、分层指标元数据、Catalog/Multi-turn 摘要和 fail-closed Release Gate。
- `apps/web/src/components/EvalDashboard.tsx`：Hard / Multi-turn / Catalog 独立分母展示，缺失证据显示 `N/A`。
- `src/harness/multiturn_dashboard.py`：多轮报告白名单投影，排除 reference solution、隐藏 gold、内部 prompt、工具参数和完整运行时元数据。
- `apps/api/main.py`：`/v1/multiturn-reports` 列表、详情、Dashboard 和按 scenario 的逐条 Trace 只读 API，固定 artifact 根目录并使用 basename allowlist。
- `apps/web/src/components/MultiTurnExplorer.tsx`：多轮报告选择、聚合指标、对话列表和逐轮 Intent/Agent 状态时间线。
- `src/harness/user_simulator.py` / `multiturn_runner.py`：独立 OpenAI-compatible User Simulator Provider 和 CLI 配置入口；默认仍为 deterministic，真实调用需要显式 Provider 参数和环境变量。
- `src/harness/deterministic_runtime.py`：`long_tail_response_0001`～`00026` 全部受控 fixture。
- `src/harness/multiturn_judge.py` / `evals/multiturn_zh/rubrics.json`：独立 Multi-turn Judge、结构化 rubric、输入脱敏、失败 fail-closed 和 usage/latency 预留字段。
- `src/harness/catalog_split.py`：按 seed family 生成互斥且穷尽的 Calibration/Frozen Candidate/Held-out/Candidate 分区；当前商品专项为 `60/120/30/90` 条 Scenario。
- `src/harness/catalog_multiturn.py` / `catalog_multiturn_runner.py`：将公开候选卡片适配为 `ScenarioSpec`，通过 `MultiTurnRunner` 接入 deterministic pilot 或显式 live Agent Runtime；live 未授权/未配置时逐条 `incomplete`。
- `catalog_multiturn_runner` 支持 `--agent-timeout`、`--scenario-timeout`、`--scenario-id`、`--limit` 和 `--profile-output`，真实 Provider 诊断可控终止；Agent turn 超时原因会保留在逐轮 Trace 和终止原因中，Catalog 生成的 Profile 可独立持久化并按 `profile_id` 追溯。
- `src/harness/static_baseline.py` 与 `scripts/compare_static_baseline.py` 提供静态报告的 canonical comparison；当前稳定契约比较结果写入 `artifacts/evals/static-baseline-judge-repro-v3-20260921/comparison.json`。
- `compare_static_baseline.py` 只有在 Hard/runtime 与 Judge-dependent 证据均可比时才返回退出码 `0`；仅有 `invariant_preserved` 但 `evidence_status=incomplete` 的比较会返回 `1`，避免被 CI 误当作完整基线通过。
- `src/harness/layered_evidence.py` 与 `scripts/audit_layered_evaluation.py` 提供计划级只读审计，要求人工复核、300 cases/900 attempts、同签名 Judge 和 Final Pass 一致性同时成立；当前审计写入 `artifacts/evals/static-baseline-judge-repro-v3-20260921/layered-evidence-audit.json`，状态为 `incomplete`，阻塞原因已明确列出。
- 根据项目负责人明确要求，`audit_layered_evaluation.py` 新增 `--skip-human-review --waiver-reason` 的自动化审计模式；该模式记录 `human_review_policy.status=waived`，不生成人工 labels，也不将 `release_gate` 改为通过。当前自动化审计写入 `artifacts/evals/static-baseline-judge-repro-v3-20260921/layered-evidence-audit-automated-only.json`，剩余阻塞为同签名 Judge 基线和 Final Pass 可比性。
- `src/harness/judge.py` 的 static Judge 输入改为显式稳定投影，排除 `run_id`、`response_present` 和多轮观测字段；`tests/harness/test_judge.py` 验证这些运行时字段不会改变 `input_hash`。
- Judge 对 malformed/provider error 使用带指数退避的有界 3 次尝试，并将 `max_attempts` 与 `retry_backoff_seconds` 纳入 secret-free config hash；缺失结果仍保持 `incomplete`，不能被默认为通过。
- `src/harness/multiturn_review.py`、`scripts/build_multiturn_review_queue.py` 和 `scripts/validate_multiturn_review.py` 生成并校验不含 `reference_solution`、target intent、Verifier 状态和 Judge 字段的人工复核队列；队列按 scenario family 稳定轮询抽样，优先保留多轮轨迹，要求 scenario 唯一且最终投影有可审阅 turns，label 要求非空 reviewer/notes 元数据并严格覆盖队列，不接受重复或越界 label。当前 v2 队列有 20 条，覆盖 `after_sale`、`compound`、`order`、`product`、`safety`、`social` 六类，其中 14 条为两轮、6 条为一轮，写入 `artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/human-review-queue.json`；标签缺失时的 stats 写入相邻 `human-review-stats.json` 并保持 `incomplete`。
- `src/harness/multiturn_dashboard.py` 与 `apps/api/main.py` 将相邻 `human-review-stats.json` 投影为白名单聚合字段；缺失 sidecar 时 API 和 `MultiTurnExplorer` 显示 `incomplete`/`0`，不暴露 labels 路径、备注或评测隐藏字段。

## 运行证据

命令均在 `commerce` Conda 环境执行：

```bash
PYTHONPATH=/home/CommerceAgent conda run -n commerce pytest -q
# 467 passed, 64 skipped

cd apps/web
npm run typecheck
npm test -- --run
npm run build
npm run lint
# 24 frontend tests passed; typecheck, build and lint passed
```

```bash
conda run -n commerce pytest -q \
  tests/unit/test_multiturn_dashboard.py \
  tests/unit/test_eval_report_paths.py \
  tests/harness/test_multiturn_runner.py \
  tests/harness/test_user_simulator.py \
  tests/harness/test_intent_state.py
# 23 passed; API path safety, missing reports, allowlisted projection, trace redaction and Provider fail-closed behavior covered
```

```bash
conda run -n commerce pytest -q \
  tests/harness/test_multiturn_judge.py \
  tests/harness/test_multiturn_runner.py \
  tests/harness/test_user_simulator.py \
  tests/unit/test_multiturn_dashboard.py \
  tests/harness/test_catalog_split.py
# 19 passed; Judge aggregation, report projection, Provider fail-closed behavior and seed-family splits covered
```

```bash
conda run -n commerce pytest -q \
  tests/harness/test_catalog_multiturn.py \
  tests/harness/test_multiturn_runner.py
# 7 passed; catalog public-context adaptation, initial messages and Agent
# turn failure fail-closed behavior covered
```

```bash
python -m src.harness.multiturn_runner \
  --dataset evals/multiturn_zh/pilot.jsonl \
  --output-dir artifacts/evals/multiturn_pilot_cli
# 30/30 completed; intent coverage 1.0; task success 1.0; evaluation noise 0

python -m src.harness.catalog_runner \
  --products evals/long_tail_zh/products.csv \
  --qa evals/long_tail_zh/qa_eval.csv \
  --track catalog_selection_v1 \
  --output-dir artifacts/evals/catalog_selection_baseline
# 99 selection cases; lexical baseline Top-1 31/99; this is not full-catalog recall

python -m src.harness.catalog_runner \
  --products evals/long_tail_zh/products.csv \
  --qa evals/long_tail_zh/qa_eval.csv \
  --track catalog_safety_v1 \
  --output-dir artifacts/evals/catalog_safety_baseline
# 1/1 safety de-escalation passed with required warning and forbidden-action checks

python -m src.harness.catalog_runner \
  --products evals/long_tail_zh/products.csv \
  --qa evals/long_tail_zh/qa_eval.csv \
  --track catalog_multiturn_v1 \
  --split held_out \
  --split-manifest artifacts/evals/catalog_multiturn/catalog-splits.json \
  --output-dir artifacts/evals/catalog_multiturn/held_out
# 30 held-out scenarios enumerated; no Runtime response supplied, report remains incomplete
```

```bash
PYTHONPATH=/home/CommerceAgent conda run -n commerce \
  python -m src.harness.catalog_multiturn_runner \
  --products evals/long_tail_zh/products.csv \
  --qa evals/long_tail_zh/qa_eval.csv \
  --split held_out \
  --split-manifest artifacts/evals/catalog_multiturn/catalog-splits.json \
  --agent-runtime deterministic_pilot \
  --output-dir <temporary-output>
# 30/30 completed as deterministic_catalog_pilot; this is only a Runner
# contract smoke test, not live Agent evidence

PYTHONPATH=/home/CommerceAgent conda run -n commerce \
  python -m src.harness.catalog_multiturn_runner \
  --products evals/long_tail_zh/products.csv \
  --qa evals/long_tail_zh/qa_eval.csv \
  --split held_out \
  --split-manifest artifacts/evals/catalog_multiturn/catalog-splits.json \
  --agent-runtime live \
  --output-dir <temporary-output>
# exit 2; 30/30 incomplete; agent_config.status=unavailable because
# --allow-live was not supplied

PYTHONPATH=/home/CommerceAgent conda run -n commerce \
  python -m src.harness.catalog_multiturn_runner \
  --products evals/long_tail_zh/products.csv \
  --qa evals/long_tail_zh/qa_eval.csv \
  --agent-runtime deterministic_pilot \
  --profile-output artifacts/evals/catalog_multiturn/catalog-profiles-20260922.jsonl \
  --output-dir artifacts/evals/catalog_multiturn/deterministic_pilot_20260922
# 300/300 completed as deterministic_catalog_pilot;
# profile_artifact.count=300; this validates scenario/profile expansion and
# Runner contract only, not live Agent evidence
```

```bash
PYTHONPATH=/home/CommerceAgent conda run -n commerce \
  python -m src.harness.multiturn_runner \
  --dataset evals/multiturn_zh/pilot.jsonl \
  --output-dir <temporary-output> \
  --judge on
# exit 2; 30 scenarios, evaluated_count 0, judge status incomplete,
# judge_config status unavailable
```

独立 Judge 已通过当前 backend Settings 映射到 Multi-turn Judge CLI。v1 运行结果保留为历史证据：

```text
report: artifacts/evals/multiturn_pilot_judge_20260921/multiturn-report.json
judge_config.status: configured
judge_config.model: deepseek-chat
judge.status: complete
judge.scenario_count / evaluated_count / error_count: 30 / 30 / 0
judge.passed / failed: 5 / 25
judge.mean_weighted_score: 1.715
```

随后重跑 Pilot v2，验证了受控 `behavior_facts` 释放和 deterministic Agent 的缺槽位追问路径：

```text
report: artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/multiturn-report.json
status: completed
scenario_count / completed_count: 30 / 30
turn counts: 1 turn=10, 2 turns=20
evaluation_noise: 0
task_success_rate: 30/30 (1.0; deterministic verifier projection)
judge_config.status: configured
judge_config.model: deepseek-chat
judge_config_hash: sha256:c134726800c90b45ecd414a758fa2149cf23cb8c06ebd07c196706d4bdbd0fc6
judge.status: complete
judge.scenario_count / evaluated_count / error_count: 30 / 30 / 0
judge.passed / failed: 5 / 25
judge.mean_weighted_score: 2.0883
```

两次结果都证明独立 Judge 和 Multi-turn Rubric 评分链路可用，但不是被测 Agent 的生产成功率。v2 Judge 仍识别出 deterministic Pilot 的占位回复与过早终止；因此 `task_success_rate=1.0` 只能解释为当前 verifier 的结构化结果，不能替代 Judge 质量结论。

静态主集按同一 `cases.jsonl`、同一 runtime fixture 重跑 3 repetitions：

```text
hard baseline report: artifacts/evals/static-baseline-20260921/report.json
dataset_hash: unchanged
selected/completed cases: 300 / 300
attempts: 900
track selected: intent_route=150, scripted_clarification=20,
  tool_workflow=60, rag_grounding=50, guardrail_handoff=20
track attempts: 450 / 60 / 180 / 150 / 60
hard_passed_cases: 300
comparison status: invariant_preserved
```

随后使用当前 Agent/Classifier/Judge 配置执行了完整 Judge-on 重跑。加入退避和稳健 JSON 对象解析后，最新完整运行写入 `artifacts/evals/static-baseline-judge-repro-v3-20260921/report.json`：900 attempts、Hard `300/300`、450 条 Judge input hash 全部存在且无 `judge_error`，报告状态为 `completed`，`passed_cases=295`。当前实现将 `max_attempts` 与 `retry_backoff_seconds` 纳入 `judge_config_hash`，并由 `JudgeConfig` 驱动；该历史 artifact 不被改写。

```text
historical release: 900 attempts, hard 300/300, Final Pass 296/300, status completed
latest stable-contract run: 900 attempts, hard 300/300, Final Pass 295/300, Judge input hashes 450/450 match, status completed
comparison: artifacts/evals/static-baseline-judge-repro-v3-20260921/comparison.json
comparison evidence_status: incomplete; comparison_scope: hard_runtime_only
comparison CLI exit code: 1 when `evidence_status=incomplete`; Hard/runtime invariants alone do not pass the complete-evidence gate.
Final Pass conclusion: N/A because historical Judge signature lacks the current config/rubric hashes; observed Final Pass is 295/300 rather than the historical 296/300.
```

此前 `static-baseline-judge-20260921` 和 `static-baseline-judge-stable-20260921` 的完整报告分别使用了不稳定/未包含 `schema_version` 的 Judge 输入投影，不作为最终基线比较证据；稳定投影修复和 hash 回归测试已补齐。外部 Judge 在相同输入下仍表现出非确定性，因此不能声称 Judge-dependent Final Pass 数值“不发生变化”。

受控单 Case 重试 `guardrail_cross_account_004` 在不同外部调用批次中出现过 `judge_error / judge_pass / judge_pass` 和 `judge_pass / judge_error / judge_error`；这证明 Provider 输出存在非确定性，后续有效响应不能覆盖前一次缺失结果，报告继续保持 `incomplete`。

当前环境已检测到 Agent/Classifier/PostgreSQL 配置；独立 User Simulator 配置仍缺失，Judge 配置已通过 backend Settings 映射验证。一次单场景 live 诊断使用 `--allow-live --limit 1 --agent-timeout 5`，结果为：

```text
exit 2
status incomplete
scenario_count 1 / incomplete_count 1
termination_reason agent_turn_timeout
agent_config.status configured
judge_config.status disabled
```

该结果证明真实 Runtime 入口和超时 fail-closed 链路已执行，但不构成 live 成功率或 Judge 证据。

2026-10-04 追加了 Judge 兼容性修复和同协议基线重放。部分 OpenAI-compatible
Provider 会返回只包含当前 rubric 维度分数的 JSON；`RubricJudge` 现在仅在键集合
完全等于 rubric 维度且所有分数为 0--4 整数时补齐 Judge envelope，其他非法输出仍
保持 fail-closed。该修复已用 `guardrail_cross_account_004` 的真实 3 次运行验证。

使用相同的当前 Judge config、稳定 trace 投影和 runtime fixture，旧 Runtime 与当前
Runtime 各完成 300 cases / 900 attempts：

```text
baseline: artifacts/evals/static-baseline-current-contract-20261004-baseline/report.json
current:  artifacts/evals/static-baseline-current-contract-20261004-current/report.json
both status: completed
both Judge errors: 0
Judge input hashes: 450/450, matching=450
Judge config hash: sha256:c134726800c90b45ecd414a758fa2149cf23cb8c06ebd07c196706d4bdbd0fc6
Hard pass: 300/300 on both reports
Final Pass: baseline 293/300, current 295/300
comparison evidence_status: complete; comparison_scope: hard_runtime_and_judge
```

Final Pass 的 2 分差异与此前 293--295 的重复重放范围一致，属于外部 Judge
非确定性；在没有明确修改计划门禁的授权前，不能将其标记为 unchanged 或 release
通过。自动化审计因此只剩 `final_pass_unchanged` 阻塞，人工复核仍记录为显式 waiver：
`artifacts/evals/static-baseline-current-contract-20261004-baseline/layered-evidence-audit-automated-only.json`。

## 尚未完成

- Pilot 仍使用 deterministic rule provider；独立 OpenAI-compatible Provider 已接入并通过 mock HTTP 合同测试，但当前环境未配置真实 Provider，因此没有宣称 live 成功率、usage、成本或时延。
- Calibration 60、Frozen Candidate 120、Held-out 30、Candidate 90 的 seed-family 分区已生成并写入 `artifacts/evals/catalog_multiturn/catalog-splits.json`；至少 20 条人工轨迹抽样复核尚未完成，v2 已生成 20 条 `pending_human_review` 队列并写入 `artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/human-review-queue.json`。
- `catalog_multiturn_v1` 已生成并持久化 100 × 3 的 Scenario/Profile（`artifacts/evals/catalog_multiturn/catalog-profiles-20260922.jsonl`，300 条）；但没有把 300 条场景全部接入真实 Agent Runtime 执行，deterministic smoke 不作为 live 能力证据，Held-out 报告因此保持 `incomplete`。
- `catalog_multiturn_runner` 已能把场景送入真实 `LiveCaseRuntime`；当前 Agent/Classifier/PostgreSQL 配置存在，但请求在受控预算内超时，尚未获得可计入成功率的真实 Agent 轨迹，Held-out live 报告保持 `incomplete`。
- 独立 User Simulator 配置仍缺失，因此真实多轮 User Simulator 轨迹、usage/成本/时延统计仍不可用；v2 使用 deterministic rule provider 完成 30 条 Pilot，独立 Judge 配置已存在并完成 30 条评分，但 Judge usage/成本只能作为本次具体评分的观测值，不能外推生产资源指标。
- 专用多轮报告 API、每个意图状态时间线、逐条 Multi-turn JSON 下钻页面和独立 Judge 接口已接入；当前仍未提供真实 Agent/User Simulator Provider 轨迹，Judge 已有 30 条真实评分轨迹。
- Judge 的 mock 合同与 fail-closed 行为已有测试；真实 Judge 本次 30 条评分已完成，但不代表 Agent 或 User Simulator 的真实线上运行结果。
- 真实 Agent/User Simulator Provider 轨迹、生产成本/时延和人工安全标签缺失时仍保持 `N/A`/`incomplete`，没有用 deterministic 或不完整 Judge 结果替代真实线上结论。
