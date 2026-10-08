# 长尾数据质量审核

当前版本为 `frozen-candidate`，共 26 条，7 个 seed family；development/test 按 family 隔离，全部为项目合成文本；尚未授权进入 Skill Registry。

本次新增 `long_tail_response_0007`～`long_tail_response_0026` 共 20 条。结构合同和 Synthetic Critic 校验通过；当前 deterministic runtime 仍只覆盖 0001～0006，新增样本需要补充独立 fixture 或接入真实 Runtime 后才能形成可运行评测结果。

本地 validator 检查 schema、PII/密钥、重复 ID、近重复 prompt 和长尾风险边界。LLM Critic 与真人抽检必须在发布前补齐；本文件不把候选状态当作审批结论。
