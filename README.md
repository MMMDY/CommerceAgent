# CommerceAgent

自研电商客服 Agent 的 internal beta 原型（mock business data）。架构、阶段门禁和运行约束见：

- [`docs/plan/feasibility-and-implementation-plan.md`](docs/plan/feasibility-and-implementation-plan.md)
- [`docs/plan/phased-implementation-execution-plan.md`](docs/plan/phased-implementation-execution-plan.md)

所有 Python 命令必须在 Conda `commerce` 环境中运行。复制 `.env.example` 为 `.env` 后，为数据库和模型填入真实配置；不要将 `.env` 提交到 Git。

## 本地启动

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
docker compose up -d --build
docker compose --profile maintenance run --rm migrate
curl http://127.0.0.1:19473/health/ready
```

前端与 API 共用 `127.0.0.1:19473`，PostgreSQL 只在 Compose 内部网络暴露。浏览器打开 <http://127.0.0.1:19473/>；评测面板为 `/evals`。

## 评测

```bash
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --judge off --repetitions 3
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --judge on --mode debug --output-dir evals/reports/<run-id>
```

`--mode release` 要求独立的 `JUDGE_MODEL/JUDGE_API_BASE/JUDGE_API_KEY` 和 30 条校准一致率 ≥90%；同候选 Agent 的 debug 自评仅标记 `provisional`，不会形成发布门禁。

## 运维

- 备份/恢复：`scripts/backup_db.sh`、`scripts/restore_db.sh`，详见 [`docs/runbooks/backup-restore.md`](docs/runbooks/backup-restore.md)。
- 故障恢复：[`docs/runbooks/failure-recovery.md`](docs/runbooks/failure-recovery.md)。
- 安全边界：[`docs/runbooks/security.md`](docs/runbooks/security.md)。
- 短时资源观测：`scripts/soak_monitor.sh --duration 10m --interval 30 --output evals/reports/soak.json --detach`。
- 报告清理默认只做 dry-run：`scripts/cleanup_reports.sh --days 30`。
