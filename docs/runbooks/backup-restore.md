# 备份与恢复演练

备份使用 PostgreSQL custom format，输出文件权限为 `0600`。脚本只读取调用者已经注入的 `DATABASE_MIGRATION_URL`/`DATABASE_URL`，不会读取或打印密钥。

```bash
mkdir -p backups
DATABASE_MIGRATION_URL='postgresql://...' scripts/backup_db.sh --output backups/commerce-agent.dump
scripts/restore_db.sh --input backups/commerce-agent.dump --target-url 'postgresql://empty-target'
```

恢复目标必须是明确指定的空实例和有建 schema 权限的数据库 owner；脚本不隐式执行 `DROP DATABASE` 或清空未知路径。演练验收查询：

- `conversation.conversations` 与 `conversation.messages` 行数一致可关联；
- `runtime.agent_runs`、`runtime.run_checkpoints`、`runtime.run_events` 外键关系完整；
- `runtime.confirmation_tokens`、`runtime.idempotency_records` 状态可重建；
- `evaluation.eval_runs` 与 case/judge 结果按批次可查询。
