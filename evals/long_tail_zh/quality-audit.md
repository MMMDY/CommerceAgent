# 长尾数据质量审核

当前版本为 `frozen-candidate`，共 6 条，5 个 seed family；development/test 按 family 隔离，全部为项目合成文本；尚未授权进入 Skill Registry。

本地 validator 检查 schema、PII/密钥、重复 ID、近重复 prompt 和长尾风险边界。LLM Critic 与真人抽检必须在发布前补齐；本文件不把候选状态当作审批结论。
