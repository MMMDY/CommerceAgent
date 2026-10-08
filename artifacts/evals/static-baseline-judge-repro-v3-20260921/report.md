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

总 case：300
最终通过：295

## Track 指标

| Track | Cases | Hard 通过 | Judge 通过 | Final 通过 |
|---|---:|---:|---:|---:|
| intent_route | 150 | 150 | 0 | 150 |
| tool_workflow | 60 | 60 | 57 | 57 |
| rag_grounding | 50 | 50 | 50 | 49 |
| scripted_clarification | 20 | 20 | 20 | 20 |
| guardrail_handoff | 20 | 20 | 19 | 19 |

## Judge 指标平均分

评分范围为 0～4 分；平均分按每次 Judge 评估计算，重复运行按 attempt 分别计入。

| 范围 | 指标 | 样本数 | 平均分 |
|---|---|---:|---:|
| overall | clarity | 330 | 3.8636 |
| overall | confirmation_clarity | 180 | 3.9278 |
| overall | no_false_claim | 240 | 3.9708 |
| overall | task_progress | 180 | 3.9556 |
| overall | evidence_grounding | 150 | 3.9533 |
| overall | factual_correctness | 150 | 3.9533 |
| overall | question_coverage | 150 | 3.9667 |
| overall | answerability | 60 | 3.8167 |
| overall | asks_needed_attribute | 60 | 4.0000 |
| overall | context_relevance | 60 | 4.0000 |
| overall | naturalness | 60 | 3.4833 |
| overall | professional_tone | 60 | 3.0000 |
| overall | safe_next_step | 60 | 2.0000 |
| overall | safety_policy | 60 | 3.6833 |
| tool_workflow | clarity | 180 | 3.7500 |
| tool_workflow | confirmation_clarity | 180 | 3.9278 |
| tool_workflow | no_false_claim | 180 | 3.9611 |
| tool_workflow | task_progress | 180 | 3.9556 |
| rag_grounding | clarity | 150 | 4.0000 |
| rag_grounding | evidence_grounding | 150 | 3.9533 |
| rag_grounding | factual_correctness | 150 | 3.9533 |
| rag_grounding | question_coverage | 150 | 3.9667 |
| scripted_clarification | answerability | 60 | 3.8167 |
| scripted_clarification | asks_needed_attribute | 60 | 4.0000 |
| scripted_clarification | context_relevance | 60 | 4.0000 |
| scripted_clarification | naturalness | 60 | 3.4833 |
| guardrail_handoff | no_false_claim | 60 | 4.0000 |
| guardrail_handoff | professional_tone | 60 | 3.0000 |
| guardrail_handoff | safe_next_step | 60 | 2.0000 |
| guardrail_handoff | safety_policy | 60 | 3.6833 |

## Judge 加权总分平均分

| 范围 | 样本数 | 平均分 |
|---|---:|---:|
| overall | 450 | 3.8609 |
| tool_workflow | 180 | 3.9281 |
| rag_grounding | 150 | 3.9613 |
| scripted_clarification | 60 | 3.9117 |
| guardrail_handoff | 60 | 3.3575 |

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
| overall | judge_latency_ms | 450 | 1363.1244 | 1324.0000 | 1807.1000 | 2667.7300 |
| overall | judge_total_tokens | 450 | 1119.0489 | 1101.0000 | 1211.0000 | 2117.4400 |
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
| tool_workflow | judge_latency_ms | 180 | 1433.9222 | 1411.0000 | 1744.0500 | 2205.2400 |
| tool_workflow | judge_total_tokens | 180 | 1159.2389 | 1157.0000 | 1223.1500 | 1249.9400 |
| tool_workflow | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | judge_latency_ms | 150 | 1177.8067 | 1168.0000 | 1519.1000 | 1682.7300 |
| rag_grounding | judge_total_tokens | 150 | 1069.8867 | 1062.5000 | 1138.5500 | 1166.0600 |
| rag_grounding | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | judge_latency_ms | 60 | 1266.2167 | 1232.5000 | 1637.1000 | 1870.3700 |
| scripted_clarification | judge_total_tokens | 60 | 1076.4667 | 1071.0000 | 1138.2500 | 1148.4100 |
| scripted_clarification | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | judge_latency_ms | 60 | 1710.9333 | 1602.0000 | 3106.8500 | 3678.4600 |
| guardrail_handoff | judge_total_tokens | 60 | 1163.9667 | 1070.0000 | 2139.3000 | 2173.3000 |
| guardrail_handoff | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |

## Hard Dimension 分层指标

每个指标保留独立分子、分母和证据状态；商品封闭候选与多轮指标不并入静态总通过率。

| Track | 维度 | 分子 | 分母 | 通过率 | Evidence |
|---|---|---:|---:|---:|---|
| intent_route | intent | 450 | 450 | 1.0000 | complete |
| intent_route | route | 450 | 450 | 1.0000 | complete |
| tool_workflow | intent | 180 | 180 | 1.0000 | complete |
| tool_workflow | route | 180 | 180 | 1.0000 | complete |
| tool_workflow | next_action | 180 | 180 | 1.0000 | complete |
| tool_workflow | tool | 180 | 180 | 1.0000 | complete |
| tool_workflow | args | 180 | 180 | 1.0000 | complete |
| tool_workflow | confirmation | 180 | 180 | 1.0000 | complete |
| tool_workflow | owner | 144 | 144 | 1.0000 | complete |
| rag_grounding | route | 150 | 150 | 1.0000 | complete |
| rag_grounding | evidence | 150 | 150 | 1.0000 | complete |
| rag_grounding | facts | 150 | 150 | 1.0000 | complete |
| scripted_clarification | route | 60 | 60 | 1.0000 | complete |
| scripted_clarification | next_action | 60 | 60 | 1.0000 | complete |
| scripted_clarification | required_slot_question | 60 | 60 | 1.0000 | complete |
| guardrail_handoff | route | 60 | 60 | 1.0000 | complete |
| guardrail_handoff | outcome | 60 | 60 | 1.0000 | complete |

## RAG Evidence 指标

| 指标 | 分子 | 分母 | 比率 | Evidence |
|---|---:|---:|---:|---|
| recall_at_k | 216 | 216 | 1.0000 | complete |
| precision_at_k | 216 | 216 | 1.0000 | complete |
| grounding_rate | 150 | 150 | 1.0000 | complete |
