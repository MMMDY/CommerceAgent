# CommerceAgent 故障恢复手册

本项目是 `internal beta / mock business data`。任何真实退款、取消或换货都不得在此环境执行。

## 快速判断

1. 查看 `docker compose ps` 与 `curl -fsS http://127.0.0.1:19473/health/live`。
2. `ready` 返回 503 时只记录非敏感 reason；不要在日志或工单中复制 `.env`。
3. 若 run 处于 `waiting_confirmation`，先确认 token 是否过期；过期只能刷新，不得重放旧 token。
4. `unknown`/超时的写工具结果必须转人工接管，禁止再次自动 commit。

## 重启流程

```bash
docker compose restart app
curl -fsS http://127.0.0.1:19473/health/ready
```

数据库重启后等待 `pg_isready` 通过，再检查会话、run、checkpoint 和事件是否仍可查询。恢复失败时保留数据库和容器日志，使用脱敏事件 ID 申请人工处理。

## 评测任务

通过 `POST /v1/evals/{eval_run_id}/cancel` 取消批次；报告状态应为 `cancelled`。报告目录仅保留 `report.json/report.md`，用 `scripts/cleanup_reports.sh` 做默认 dry-run 后再按审批执行清理。
