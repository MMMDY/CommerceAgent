# CommerceAgent 评测报告

状态：`incomplete`

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

总 case：300
最终通过：295

## Track 指标

| Track | Cases | Hard 通过 | Judge 通过 | Final 通过 |
|---|---:|---:|---:|---:|
| intent_route | 150 | 150 | 0 | 150 |
| tool_workflow | 60 | 60 | 60 | 58 |
| rag_grounding | 50 | 50 | 50 | 49 |
| scripted_clarification | 20 | 20 | 20 | 20 |
| guardrail_handoff | 20 | 20 | 19 | 18 |

## Judge 指标平均分

评分范围为 0～4 分；平均分按每次 Judge 评估计算，重复运行按 attempt 分别计入。

| 范围 | 指标 | 样本数 | 平均分 |
|---|---|---:|---:|
| overall | clarity | 330 | 3.9030 |
| overall | confirmation_clarity | 180 | 3.9667 |
| overall | no_false_claim | 239 | 3.9916 |
| overall | task_progress | 180 | 3.9833 |
| overall | evidence_grounding | 150 | 3.9533 |
| overall | factual_correctness | 150 | 3.9533 |
| overall | question_coverage | 150 | 3.9667 |
| overall | asks_needed_attribute | 60 | 4.0000 |
| overall | context_relevance | 60 | 4.0000 |
| overall | answerability | 60 | 3.8000 |
| overall | naturalness | 60 | 3.4667 |
| overall | professional_tone | 59 | 3.0000 |
| overall | safe_next_step | 59 | 2.0000 |
| overall | safety_policy | 59 | 3.6610 |
| tool_workflow | clarity | 180 | 3.8222 |
| tool_workflow | confirmation_clarity | 180 | 3.9667 |
| tool_workflow | no_false_claim | 180 | 3.9889 |
| tool_workflow | task_progress | 180 | 3.9833 |
| rag_grounding | clarity | 150 | 4.0000 |
| rag_grounding | evidence_grounding | 150 | 3.9533 |
| rag_grounding | factual_correctness | 150 | 3.9533 |
| rag_grounding | question_coverage | 150 | 3.9667 |
| scripted_clarification | asks_needed_attribute | 60 | 4.0000 |
| scripted_clarification | context_relevance | 60 | 4.0000 |
| scripted_clarification | answerability | 60 | 3.8000 |
| scripted_clarification | naturalness | 60 | 3.4667 |
| guardrail_handoff | no_false_claim | 59 | 4.0000 |
| guardrail_handoff | professional_tone | 59 | 3.0000 |
| guardrail_handoff | safe_next_step | 59 | 2.0000 |
| guardrail_handoff | safety_policy | 59 | 3.6610 |

## Judge 加权总分平均分

| 范围 | 样本数 | 平均分 |
|---|---:|---:|
| overall | 449 | 3.8743 |
| tool_workflow | 180 | 3.9636 |
| rag_grounding | 150 | 3.9613 |
| scripted_clarification | 60 | 3.9067 |
| guardrail_handoff | 59 | 3.3475 |

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
| overall | judge_latency_ms | 450 | 1337.7778 | 1269.0000 | 1776.1000 | 3322.9400 |
| overall | judge_total_tokens | 449 | 1121.4321 | 1102.0000 | 1204.2000 | 2112.6800 |
| overall | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| overall | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| intent_route | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| intent_route | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| intent_route | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| intent_route | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| intent_route | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| intent_route | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| intent_route | judge_latency_ms | 0 | N/A | N/A | N/A | N/A |
| intent_route | judge_total_tokens | 0 | N/A | N/A | N/A | N/A |
| intent_route | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| intent_route | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | judge_latency_ms | 180 | 1370.5667 | 1346.0000 | 1756.9500 | 1873.6100 |
| tool_workflow | judge_total_tokens | 180 | 1149.5889 | 1157.0000 | 1214.0000 | 1221.4200 |
| tool_workflow | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | judge_latency_ms | 150 | 1150.4800 | 1125.5000 | 1578.6000 | 1690.0400 |
| rag_grounding | judge_total_tokens | 150 | 1071.2533 | 1070.0000 | 1138.1000 | 1168.0000 |
| rag_grounding | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | judge_latency_ms | 60 | 1288.0833 | 1250.0000 | 1688.1500 | 1953.9000 |
| scripted_clarification | judge_total_tokens | 60 | 1080.5833 | 1079.0000 | 1144.1500 | 1164.8100 |
| scripted_clarification | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | judge_latency_ms | 60 | 1757.3500 | 1563.5000 | 3558.8500 | 5056.8600 |
| guardrail_handoff | judge_total_tokens | 59 | 1204.6441 | 1080.0000 | 2132.1000 | 2612.2800 |
| guardrail_handoff | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
