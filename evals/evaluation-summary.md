# CommerceAgent 评测结果综合汇总

> 汇总时间：2026-10-04（Asia/Shanghai）  
> 汇总范围：`/home/CommerceAgent/artifacts/evals` 中已生成的静态评测、多轮评测、商品长尾、RAG、Judge 诊断和计划级门禁证据。  
> 说明：重复重放属于同一评测合同下的独立观察，不合并为更大的样本量；`N/A` 或 `incomplete` 不解释为通过。

## 1. 总体结论

| 领域 | 最新证据 | 结果 | 状态 |
|---|---|---:|---|
| 静态 Hard baseline | 300 cases × 3 repetitions | Hard `300/300`，900 attempts | 通过 |
| 静态 Judge 对照 | 当前 Judge 合同下旧 Runtime vs 当前 Runtime | `293/300` vs `295/300` | 可比但 Final Pass 未保持完全一致 |
| 多轮 deterministic Pilot | 30 scenarios | 30/30 completed，task success `30/30` | 通过合同，不代表线上成功率 |
| 商品选择 | 封闭候选集 | Top-1 `31/99`，约束满足 `2/99` | 完成，非全库检索 |
| 商品安全 | `none_of_candidates` | `1/1` | 通过 |
| 商品多轮 deterministic Pilot | 100 seeds × 3 profiles | `300/300` completed | 通过 Runner 合同，不代表 live 能力 |
| RAG baseline | 50 cases | Hard `50/50`，Recall/Precision/Grounding 均 `1.0` | deterministic 通过 |
| 人工核验 | 最少 20 条 | 明确豁免，未收集 labels | `waived` |
| 计划级 Release Gate | 自动化审计 | `automated_gate=false`，`release_gate=false` | `incomplete` |

当前不能宣称“计划完全通过”：唯一剩余自动化阻塞是 Judge 非确定性造成的 `final_pass_unchanged=false`。人工核验已按要求跳过，但没有伪造人工 labels。

## 2. 静态主集评测

### 2.1 数据与 Hard 结果

| 字段 | 值 |
|---|---|
| Dataset | `cases` / `legacy` |
| Dataset hash | `240846bdb3d3dbb0b5c2b16df9df4b9d8f45a24c06bd8b77abd84910edb10ff5` |
| Runtime fixture hash | `56a7d9edae15510bbe15d0f52bcac6f549126b7078efbfdef8307acb482f8c8e` |
| Cases / repetitions / attempts | `300 / 3 / 900` |
| Hard pass | `300/300` |
| Track cases | intent 150，clarification 20，workflow 60，RAG 50，guardrail 20 |
| Track attempts | 450，60，180，150，60 |

Hard-only 基线报告：[static-baseline-20260921/report.json](../artifacts/evals/static-baseline-20260921/report.json)

### 2.2 Judge 结果及可比性

| 报告 | Judge config hash | Status | Final Pass | Judge errors | 用途 |
|---|---|---|---:|---:|---|
| 历史 release | `ddee6696…df763` | completed | `298/300` | 0（历史报告） | 历史参考；旧输入投影 |
| 稳定合同 v3 | `c1347268…d0fc6` | completed | `295/300` | 0 | 当前稳定 Judge 报告 |
| 当前协议旧 Runtime | `c1347268…d0fc6` | completed | `293/300` | 0 | 可比基线 |
| 当前协议当前 Runtime | `c1347268…d0fc6` | completed | `295/300` | 0 | 可比当前结果 |

当前协议对照证据：

- 基线：[report.json](../artifacts/evals/static-baseline-current-contract-20261004-baseline/report.json)
- 当前：[report.json](../artifacts/evals/static-baseline-current-contract-20261004-current/report.json)
- 比较：[comparison.json](../artifacts/evals/static-baseline-current-contract-20261004-baseline/comparison.json)

比较器确认：

- Dataset、shape、track shape 和 Hard pass 全部一致；
- 两份报告均 completed；
- Judge mode、model、prompt hash、rubric hash 和 config hash 一致；
- Judge input hashes `450/450` 完全匹配；
- Final Pass 存在 `293` 对 `295` 的差异，因此不能证明 exact unchanged。

### 2.3 Judge 解析修复

Provider 曾偶发返回仅包含 rubric 维度分数的 JSON，例如：

```json
{"no_false_claim": 4, "professional_tone": 3, "safe_next_step": 2, "safety_policy": 4}
```

`src/harness/judge.py` 现仅在以下条件同时满足时补齐 envelope：

1. 键集合完全等于当前 rubric 的维度名；
2. 所有值都是 0–4 的整数；
3. 当前 case 和 rubric identity 可从已构造的 Judge input 取得。

其他非法输出仍然 fail-closed。目标 case 的真实 3 次诊断运行均成功；完整重放也达到 `0 judge_error`。

## 3. 多轮 User Simulator / Intent State 评测

### 3.1 Deterministic Pilot

| 报告 | Scenarios | Completed | Intent coverage | Agenda progress | Exposed intent accuracy | Task success | Judge |
|---|---:|---:|---:|---:|---:|---:|---|
| Pilot v1 | 30 | 30 | 1.0 | 1.0 | 1.0 | `30/30` | 未启用 |
| Pilot v2 | 30 | 30 | 1.0 | 1.0 | 1.0 | `30/30` | 未启用 |
| Pilot v2 + 独立 Judge | 30 | 30 | — | — | — | `30/30` verifier projection | 5 passed / 25 failed，mean `2.0883` |

独立 Judge 结果：[multiturn-report.json](../artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/multiturn-report.json)

该 `task_success_rate=1.0` 是 deterministic verifier 的结构化结果，不是生产流量成功率。独立 Judge 的 30 条评分全部完成，但只通过 5 条，揭示了占位回复和过早终止等质量问题。

### 3.2 人工核验状态

| 项目 | 结果 |
|---|---|
| 目标 | 至少 20 条轨迹人工抽样核验 |
| 当前策略 | 显式跳过，`human_review_policy.status=waived` |
| Labels | 未生成、未伪造 |
| 原始 stats | `human_review_labels_unavailable` |
| 审计 | 人工项不阻塞 automated-only audit，但不会变成通过证据 |

最新审计：[layered-evidence-audit-automated-only.json](../artifacts/evals/static-baseline-current-contract-20261004-baseline/layered-evidence-audit-automated-only.json)

## 4. 商品长尾 / Catalog 评测

### 4.1 数据合同

| 项目 | 结果 |
|---|---:|
| 受控商品 | 500 |
| 唯一问题种子 | 100 |
| 商品选择题 | 99 |
| `none_of_candidates` 安全题 | 1 |
| Catalog profiles | 300（100 seeds × 3 profiles） |
| Profile 唯一性 | `profile_id` 唯一 |

### 4.2 封闭候选选择与安全

| Track | 分子 / 分母 | 比率 | Evidence |
|---|---:|---:|---|
| Candidate Top-1 | 31 / 99 | `0.3131` | complete |
| Constraint satisfaction | 2 / 99 | `0.0202` | complete |
| Trap rejection | 31 / 99 | `0.3131` | complete |
| None-of-candidates accuracy | 1 / 1 | `1.0` | complete |

报告：[catalog selection](../artifacts/evals/catalog_selection_baseline/catalog-report.json)、[catalog safety](../artifacts/evals/catalog_safety_baseline/catalog-report.json)

这些结果只代表受控候选集，不代表全商品库检索 Recall。商品 response grounding 没有有效分母时保持 `N/A` / `incomplete`。

### 4.3 Catalog 多轮

| 报告 | Scenarios | Completed | Intent coverage | Agenda progress | Task success | 状态 |
|---|---:|---:|---:|---:|---:|---|
| Deterministic pilot | 300 | 300 | 1.0 | 1.0 | 1.0 | completed |
| Held-out live | — | — | N/A | N/A | N/A | incomplete |

Catalog 多轮 deterministic 报告：[multiturn-report.md](../artifacts/evals/catalog_multiturn/deterministic_pilot_20260922/multiturn-report.md)

Held-out 尚未获得真实 Agent Runtime 轨迹，因此不计为线上能力：[held_out/catalog-report.json](../artifacts/evals/catalog_multiturn/held_out/catalog-report.json)

## 5. RAG 评测

| 指标 | 分子 / 分母 | 比率 |
|---|---:|---:|
| Cases | 50 / 50 completed | — |
| Hard route | 50 / 50 | `1.0000` |
| Hard evidence | 50 / 50 | `1.0000` |
| Hard facts | 50 / 50 | `1.0000` |
| Evidence recall@K | 72 / 72 | `1.0000` |
| Evidence precision@K | 72 / 72 | `1.0000` |
| Grounding rate | 50 / 50 | `1.0000` |

报告：[rag_baseline/report.md](../artifacts/evals/rag_baseline/report.md)

## 6. 诊断与重复重放记录

重复重放用于诊断 Judge/provider 行为，不作为额外独立样本：

| 组 | 代表产物 | 结果 |
|---|---|---|
| Legacy Judge 重放 | `static-baseline-legacy-repro-20261003*` | 有 completed 和 incomplete 混合结果；旧输入投影不可与稳定合同直接比较 |
| Stable input 重放 | `static-baseline-legacy-repro-20261003-stable-input*` | input hashes 可匹配，但旧 Judge 曾出现 provider parse error |
| Current contract 重放 | `static-baseline-current-contract-20261003*` | 293–295 的 Judge 方差；最新完整对照见 20261004 |
| 单 case 诊断 | `diagnostic-guardrail-cross-account-20261004*` | shorthand 输出已定位并修复 |
| Judge retry 诊断 | `judge-retry-guardrail-cross-account-004-*` | 历史上出现过 error/pass 混合，不能覆盖缺失结果 |

## 7. Release Gate 与限制

最新自动化审计状态：

```text
status: incomplete
automated_gate: false
release_gate: false
human_review_policy: waived
blocking_reasons: final_pass_unchanged
```

仍保持以下限制：

- 没有真实 User Simulator Provider 轨迹时，不宣称线上多轮覆盖率；
- 没有真实 Agent Runtime 的 Catalog held-out 轨迹时，不宣称生产商品能力；
- 没有 Provider usage / 价格数据时，成本和 token 指标显示 `N/A`；
- 没有人工 labels 时，不计算安全 false-negative / false-rejection 作为真实人工结论；
- Judge 非确定性造成的 Final Pass 差异不能被人工或脚本改写为 unchanged；
- 人工核验已跳过，但 waiver 不等于人工通过。

## 8. 主要原始产物索引

- 静态 Hard：[static-baseline-20260921](../artifacts/evals/static-baseline-20260921/)
- 稳定 Judge v3：[static-baseline-judge-repro-v3-20260921](../artifacts/evals/static-baseline-judge-repro-v3-20260921/)
- 当前协议配对重放：[static-baseline-current-contract-20261004-baseline](../artifacts/evals/static-baseline-current-contract-20261004-baseline/)
- 多轮 Pilot：[multiturn_pilot_v2_judge_settings_20260921](../artifacts/evals/multiturn_pilot_v2_judge_settings_20260921/)
- Catalog：[catalog_selection_baseline](../artifacts/evals/catalog_selection_baseline/)、[catalog_safety_baseline](../artifacts/evals/catalog_safety_baseline/)、[catalog_multiturn](../artifacts/evals/catalog_multiturn/)
- RAG：[rag_baseline](../artifacts/evals/rag_baseline/)
- 计划与验收定义：[user-simulator-and-layered-evaluation-plan.md](../docs/plan/user-simulator-and-layered-evaluation-plan.md)
