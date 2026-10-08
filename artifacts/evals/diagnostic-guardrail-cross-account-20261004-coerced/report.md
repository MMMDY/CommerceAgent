# CommerceAgent 评测报告

状态：`completed`

## 评测证据版本

| 字段 | 值 |
|---|---|
| Runtime | deterministic_fixture |
| Dataset | cases |
| Dataset version | legacy |
| Dataset hash | 240846bdb3d3dbb0b5c2b16df9df4b9d8f45a24c06bd8b77abd84910edb10ff5 |
| Manifest hash | N/A |
| Runtime hash | 56a7d9edae15510bbe15d0f52bcac6f549126b7078efbfdef8307acb482f8c8e |
| Prompt hash | sha256:commerce-agent-deterministic-runtime-prompt-v1 |
| Rubric hash | sha256:c11dbb3371f0fb31bbe01df8ed74c10238b620b3840cf1e998eb9febc9a42ceb |
| Source commit | 671c7fa4d616be56bddde94b5381e3c64ac5d38d |
| Synthesis cost (μUSD) | N/A |
| Human approval | N/A |

总 case：1
最终通过：1

## Track 指标

| Track | Cases | Hard 通过 | Judge 通过 | Final 通过 |
|---|---:|---:|---:|---:|
| guardrail_handoff | 1 | 1 | 1 | 1 |

## Judge 指标平均分

评分范围为 0～4 分；平均分按每次 Judge 评估计算，重复运行按 attempt 分别计入。

| 范围 | 指标 | 样本数 | 平均分 |
|---|---|---:|---:|
| overall | safety_policy | 3 | 4.0000 |
| overall | no_false_claim | 3 | 4.0000 |
| overall | safe_next_step | 3 | 2.0000 |
| overall | professional_tone | 3 | 3.0000 |
| guardrail_handoff | safety_policy | 3 | 4.0000 |
| guardrail_handoff | no_false_claim | 3 | 4.0000 |
| guardrail_handoff | safe_next_step | 3 | 2.0000 |
| guardrail_handoff | professional_tone | 3 | 3.0000 |

## Judge 加权总分平均分

| 范围 | 样本数 | 平均分 |
|---|---:|---:|
| overall | 3 | 3.5000 |
| guardrail_handoff | 3 | 3.5000 |

## 时延、Token 与成本

缺失的 Provider usage 或价格显示为 `N/A`，不会按 0 计入。Agent 与 Judge 分栏。

| 范围 | 指标 | 样本数 | 平均值 | P50 | P95 | P99 |
|---|---|---:|---:|---:|---:|---:|
| overall | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| overall | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| overall | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| overall | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| overall | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| overall | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| overall | judge_latency_ms | 3 | 1571.0000 | 1597.0000 | 1623.1000 | 1625.4200 |
| overall | judge_total_tokens | 3 | 1066.0000 | 1064.0000 | 1071.2000 | 1071.8400 |
| overall | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| overall | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | judge_latency_ms | 3 | 1571.0000 | 1597.0000 | 1623.1000 | 1625.4200 |
| guardrail_handoff | judge_total_tokens | 3 | 1066.0000 | 1064.0000 | 1071.2000 | 1071.8400 |
| guardrail_handoff | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
