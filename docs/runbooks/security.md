# 安全边界与发布限制

- `.env` 仅由后端读取，权限保持 `0600`，不得进入镜像、前端 bundle、trace、报告或日志。
- 用户消息、RAG 文档、ToolResult 和 Judge 输入全部视为不可信数据；它们不能扩展工具白名单、scope、owner 或状态机权限。
- Tool decision 拒绝 `tenant_id/actor_id/owner_id/scopes/idempotency_key/confirmation_token` 等系统字段。
- 所有资源访问同时校验 tenant、actor 和资源 owner；错误响应统一，不泄露资源是否存在。
- confirmation token 只在内存短暂存在，持久化只保存 hash；重复确认依靠幂等键返回已有结果。
- `scripts/check_secrets.py` 应在提交前执行；它只输出变量名/文件位置，不输出匹配值。
- Release Judge 必须使用独立模型/端点/Key；同模型自评只能是 `provisional`，不能作为发布门禁。
- 当前产物标记为 `internal beta / mock business data`，不具备生产退款执行资格。
