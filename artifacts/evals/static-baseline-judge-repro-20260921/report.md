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
最终通过：290

## Track 指标

| Track | Cases | Hard 通过 | Judge 通过 | Final 通过 |
|---|---:|---:|---:|---:|
| intent_route | 150 | 150 | 0 | 150 |
| tool_workflow | 60 | 60 | 55 | 54 |
| rag_grounding | 50 | 50 | 50 | 48 |
| scripted_clarification | 20 | 20 | 20 | 20 |
| guardrail_handoff | 20 | 20 | 19 | 18 |

## Judge 指标平均分

评分范围为 0～4 分；平均分按每次 Judge 评估计算，重复运行按 attempt 分别计入。

| 范围 | 指标 | 样本数 | 平均分 |
|---|---|---:|---:|
| overall | clarity | 330 | 3.8606 |
| overall | confirmation_clarity | 180 | 3.8889 |
| overall | no_false_claim | 238 | 3.9748 |
| overall | task_progress | 180 | 3.9444 |
| overall | evidence_grounding | 150 | 3.9533 |
| overall | factual_correctness | 150 | 3.9533 |
| overall | question_coverage | 150 | 3.9667 |
| overall | answerability | 60 | 3.7667 |
| overall | asks_needed_attribute | 60 | 4.0000 |
| overall | context_relevance | 60 | 4.0000 |
| overall | naturalness | 60 | 3.4333 |
| overall | professional_tone | 58 | 3.0000 |
| overall | safe_next_step | 58 | 2.0000 |
| overall | safety_policy | 58 | 3.6552 |
| tool_workflow | clarity | 180 | 3.7444 |
| tool_workflow | confirmation_clarity | 180 | 3.8889 |
| tool_workflow | no_false_claim | 180 | 3.9667 |
| tool_workflow | task_progress | 180 | 3.9444 |
| rag_grounding | clarity | 150 | 4.0000 |
| rag_grounding | evidence_grounding | 150 | 3.9533 |
| rag_grounding | factual_correctness | 150 | 3.9533 |
| rag_grounding | question_coverage | 150 | 3.9667 |
| scripted_clarification | answerability | 60 | 3.7667 |
| scripted_clarification | asks_needed_attribute | 60 | 4.0000 |
| scripted_clarification | context_relevance | 60 | 4.0000 |
| scripted_clarification | naturalness | 60 | 3.4333 |
| guardrail_handoff | no_false_claim | 58 | 4.0000 |
| guardrail_handoff | professional_tone | 58 | 3.0000 |
| guardrail_handoff | safe_next_step | 58 | 2.0000 |
| guardrail_handoff | safety_policy | 58 | 3.6552 |

## Judge 加权总分平均分

| 范围 | 样本数 | 平均分 |
|---|---:|---:|
| overall | 448 | 3.8536 |
| tool_workflow | 180 | 3.9133 |
| rag_grounding | 150 | 3.9613 |
| scripted_clarification | 60 | 3.8967 |
| guardrail_handoff | 58 | 3.3448 |

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
| overall | judge_latency_ms | 450 | 1369.4111 | 1337.0000 | 1825.0000 | 2837.7100 |
| overall | judge_total_tokens | 448 | 1110.3326 | 1101.0000 | 1211.0000 | 1232.5300 |
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
| tool_workflow | judge_latency_ms | 180 | 1442.1889 | 1445.0000 | 1777.8000 | 1912.4200 |
| tool_workflow | judge_total_tokens | 180 | 1153.0333 | 1162.0000 | 1221.0500 | 1233.2100 |
| tool_workflow | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | judge_latency_ms | 150 | 1152.5733 | 1129.5000 | 1471.8000 | 1631.6500 |
| rag_grounding | judge_total_tokens | 150 | 1069.4933 | 1062.5000 | 1139.0000 | 1164.0200 |
| rag_grounding | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | judge_latency_ms | 60 | 1346.3833 | 1370.5000 | 1578.1000 | 1786.0600 |
| scripted_clarification | judge_total_tokens | 60 | 1083.5500 | 1085.5000 | 1129.7000 | 1175.8300 |
| scripted_clarification | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | judge_latency_ms | 60 | 1716.2000 | 1583.0000 | 2889.0000 | 3030.6100 |
| guardrail_handoff | judge_total_tokens | 58 | 1111.1379 | 1068.5000 | 1146.6000 | 2129.7200 |
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
