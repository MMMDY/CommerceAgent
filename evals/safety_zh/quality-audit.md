# 高危数据质量审核

当前版本为 `frozen-candidate`，共 5 条，5 个 seed family；development/test 按 family 隔离，覆盖确认绕过、越权、提示注入、工具状态未知和凭据请求。

这些样本即使自动评测全部通过，也不能替代高危边界的真人批准；独立 Judge 不可用时报告必须是 `incomplete`，不得自动放行。
