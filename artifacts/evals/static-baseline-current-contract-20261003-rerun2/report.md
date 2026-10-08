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
最终通过：294

## Track 指标

| Track | Cases | Hard 通过 | Judge 通过 | Final 通过 |
|---|---:|---:|---:|---:|
| intent_route | 150 | 150 | 0 | 150 |
| tool_workflow | 60 | 60 | 57 | 57 |
| rag_grounding | 50 | 50 | 49 | 48 |
| scripted_clarification | 20 | 20 | 20 | 20 |
| guardrail_handoff | 20 | 20 | 19 | 19 |

## Judge 指标平均分

评分范围为 0～4 分；平均分按每次 Judge 评估计算，重复运行按 attempt 分别计入。

| 范围 | 指标 | 样本数 | 平均分 |
|---|---|---:|---:|
| overall | clarity | 330 | 3.8758 |
| overall | confirmation_clarity | 180 | 3.9278 |
| overall | no_false_claim | 240 | 3.9833 |
| overall | task_progress | 180 | 3.9611 |
| overall | evidence_grounding | 150 | 3.9400 |
| overall | factual_correctness | 150 | 3.9400 |
| overall | question_coverage | 150 | 3.9600 |
| overall | answerability | 60 | 3.8000 |
| overall | asks_needed_attribute | 60 | 4.0000 |
| overall | context_relevance | 60 | 4.0000 |
| overall | naturalness | 60 | 3.4500 |
| overall | professional_tone | 60 | 3.0000 |
| overall | safe_next_step | 60 | 2.0000 |
| overall | safety_policy | 60 | 3.6500 |
| tool_workflow | clarity | 180 | 3.7722 |
| tool_workflow | confirmation_clarity | 180 | 3.9278 |
| tool_workflow | no_false_claim | 180 | 3.9778 |
| tool_workflow | task_progress | 180 | 3.9611 |
| rag_grounding | clarity | 150 | 4.0000 |
| rag_grounding | evidence_grounding | 150 | 3.9400 |
| rag_grounding | factual_correctness | 150 | 3.9400 |
| rag_grounding | question_coverage | 150 | 3.9600 |
| scripted_clarification | answerability | 60 | 3.8000 |
| scripted_clarification | asks_needed_attribute | 60 | 4.0000 |
| scripted_clarification | context_relevance | 60 | 4.0000 |
| scripted_clarification | naturalness | 60 | 3.4500 |
| guardrail_handoff | no_false_claim | 60 | 4.0000 |
| guardrail_handoff | professional_tone | 60 | 3.0000 |
| guardrail_handoff | safe_next_step | 60 | 2.0000 |
| guardrail_handoff | safety_policy | 60 | 3.6500 |

## Judge 加权总分平均分

| 范围 | 样本数 | 平均分 |
|---|---:|---:|
| overall | 450 | 3.8579 |
| tool_workflow | 180 | 3.9364 |
| rag_grounding | 150 | 3.9510 |
| scripted_clarification | 60 | 3.9050 |
| guardrail_handoff | 60 | 3.3425 |

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
| overall | judge_latency_ms | 450 | 1380.5178 | 1333.5000 | 1934.8000 | 3264.7200 |
| overall | judge_total_tokens | 450 | 1126.1267 | 1102.5000 | 1213.5500 | 2139.5300 |
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
| tool_workflow | judge_latency_ms | 180 | 1415.7611 | 1387.5000 | 1809.4000 | 2007.9900 |
| tool_workflow | judge_total_tokens | 180 | 1158.9333 | 1162.5000 | 1216.2500 | 1243.4200 |
| tool_workflow | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| tool_workflow | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | judge_latency_ms | 150 | 1167.1400 | 1148.0000 | 1531.3000 | 1602.6700 |
| rag_grounding | judge_total_tokens | 150 | 1068.9133 | 1060.0000 | 1129.6500 | 1163.0000 |
| rag_grounding | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| rag_grounding | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | judge_latency_ms | 60 | 1359.6167 | 1322.5000 | 1726.4000 | 1879.6200 |
| scripted_clarification | judge_total_tokens | 60 | 1079.2833 | 1075.5000 | 1143.0000 | 1164.0200 |
| scripted_clarification | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| scripted_clarification | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | e2e_latency_ms | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_invocation_count | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_input_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_output_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_total_tokens | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | judge_latency_ms | 60 | 1829.1333 | 1604.5000 | 3303.2500 | 3630.2100 |
| guardrail_handoff | judge_total_tokens | 60 | 1217.5833 | 1073.5000 | 2141.1000 | 2147.2300 |
| guardrail_handoff | judge_cost_microusd | 0 | N/A | N/A | N/A | N/A |
| guardrail_handoff | agent_estimated_usage_ratio | 0 | N/A | N/A | N/A | N/A |
