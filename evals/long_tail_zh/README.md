# long_tail_zh

这是与 core 300 case 分离的长尾候选评测目录，当前包含两类不同用途的数据：

- `cases.jsonl`：`long_tail_response_v1` Track，共 26 条低风险社交、积极情绪、感谢、能力咨询、身份询问和结束语样本；
- `products.csv` + `qa_eval.csv`：新增商品候选判别种子集，共 500 个商品、100 个问题、每题 5 个候选，当前尚未接入现有 Runner。

- 数据集状态：`frozen-candidate`，不自动进入线上路由或 Skill Registry。当前 manifest 版本为 `2026-09-21.v2`。
- 生成器：`template-generator-v1`；每个 case 保留 `seed_family`、`prompt_hash` 和 `review_status`。
- 评测：Hard boundary + 独立 LLM as Judge；不把本数据集与 core 300 的通过率合并。
- 数据保留：文本均为项目合成样本；授权真实样本如加入，最多保留 30 天并须脱敏。

商品 CSV 的详细评测设计见：[商品长尾数据评测设计方案](../../docs/plan/long-tail-catalog-evaluation-design.md)。其中 99 个问题用于商品候选判别，1 个“消毒液与洁厕灵混用”问题属于 `none_of_candidates` 安全降级场景，不应按商品 Top-1 统计。
