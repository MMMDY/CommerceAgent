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
最终通过：294

## Track 指标

| Track | Cases | Hard 通过 | Judge 通过 | Final 通过 |
|---|---:|---:|---:|---:|
| intent_route | 150 | 150 | 0 | 150 |
| tool_workflow | 60 | 60 | 57 | 57 |
| rag_grounding | 50 | 50 | 49 | 49 |
| scripted_clarification | 20 | 20 | 20 | 20 |
| guardrail_handoff | 20 | 20 | 19 | 18 |

## Judge 指标平均分

评分范围为 0～4 分；平均分按每次 Judge 评估计算，重复运行按 attempt 分别计入。

| 范围 | 指标 | 样本数 | 平均分 |
|---|---|---:|---:|
| overall | clarity | 330 | 3.8788 |
| overall | confirmation_clarity | 180 | 3.9222 |
| overall | no_false_claim | 239 | 3.9791 |
| overall | task_progress | 180 | 3.9611 |
| overall | evidence_grounding | 150 | 3.9400 |
| overall | factual_correctness | 150 | 3.9400 |
| overall | question_coverage | 150 | 3.9600 |
| overall | answerability | 60 | 3.8000 |
| overall | asks_needed_attribute | 60 | 4.0000 |
| overall | context_relevance | 60 | 4.0000 |
| overall | naturalness | 60 | 3.4500 |
| overall | professional_tone | 59 | 3.0000 |
| overall | safe_next_step | 59 | 2.0000 |
| overall | safety_policy | 59 | 3.6780 |
| tool_workflow | clarity | 180 | 3.7778 |
| tool_workflow | confirmation_clarity | 180 | 3.9222 |
| tool_workflow | no_false_claim | 180 | 3.9722 |
| tool_workflow | task_progress | 180 | 3.9611 |
| rag_grounding | clarity | 150 | 4.0000 |
| rag_grounding | evidence_grounding | 150 | 3.9400 |
| rag_grounding | factual_correctness | 150 | 3.9400 |
| rag_grounding | question_coverage | 150 | 3.9600 |
| scripted_clarification | answerability | 60 | 3.8000 |
| scripted_clarification | asks_needed_attribute | 60 | 4.0000 |
| scripted_clarification | context_relevance | 60 | 4.0000 |
| scripted_clarification | naturalness | 60 | 3.4500 |
| guardrail_handoff | no_false_claim | 59 | 4.0000 |
| guardrail_handoff | professional_tone | 59 | 3.0000 |
| guardrail_handoff | safe_next_step | 59 | 2.0000 |
| guardrail_handoff | safety_policy | 59 | 3.6780 |

## Judge 加权总分平均分

| 范围 | 样本数 | 平均分 |
|---|---:|---:|
| overall | 449 | 3.8597 |
| tool_workflow | 180 | 3.9339 |
| rag_grounding | 150 | 3.9510 |
| scripted_clarification | 60 | 3.9050 |
| guardrail_handoff | 59 | 3.3551 |

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
| overall | judge_latency_ms | 450 | 1436.9089 | 1394.0000 | 1924.9000 | 3173.5300 |
| overall | judge_total_tokens | 449 | 1119.9688 | 1103.0000 | 1212.2000 | 2135.6000 |
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
| tool_workflow | judge_latency_ms | 180 | 1490.0944 | 1496.0000 | 1826.3500 | 2056.9000 |
| tool_workflow | judge_total_tokens | 180 | 1152.4611 | 1161.0000 | 1219.0000 | 1234.0000 |
| tool_workflow | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | judge_latency_ms | 150 | 1232.0867 | 1234.5000 | 1607.6000 | 1757.1800 |
| rag_grounding | judge_total_tokens | 150 | 1068.6667 | 1064.5000 | 1129.8000 | 1165.5500 |
| rag_grounding | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | judge_latency_ms | 60 | 1335.4833 | 1316.5000 | 1721.5500 | 1748.6600 |
| scripted_clarification | judge_total_tokens | 60 | 1082.4000 | 1080.0000 | 1145.0000 | 1157.3300 |
| scripted_clarification | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | judge_latency_ms | 60 | 1890.8333 | 1694.0000 | 3345.8000 | 4370.9800 |
| guardrail_handoff | judge_total_tokens | 59 | 1189.4746 | 1079.0000 | 2141.7000 | 2165.5600 |
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
