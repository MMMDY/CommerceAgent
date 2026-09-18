# long_tail_zh

这是与 core 300 case 分离的长尾候选评测集，覆盖低风险社交、积极情绪、感谢和能力咨询。

- 数据集状态：`frozen-candidate`，不自动进入线上路由或 Skill Registry。
- 生成器：`template-generator-v1`；每个 case 保留 `seed_family`、`prompt_hash` 和 `review_status`。
- 评测：Hard boundary + 独立 LLM as Judge；不把本数据集与 core 300 的通过率合并。
- 数据保留：文本均为项目合成样本；授权真实样本如加入，最多保留 30 天并须脱敏。
