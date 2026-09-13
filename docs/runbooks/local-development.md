# 本地开发与 Phase 0 验证

在项目根目录执行：

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce
python -m pip install -e ".[dev]"
npm ci --prefix apps/web
```

`.env` 必须仅由当前用户可读，并包含 `.env.example` 中的数据库和模型变量。不要打印、复制或提交其中的值。

运行 migration 服务后，再启动默认服务：

```bash
docker compose up -d db
docker compose --profile maintenance run --rm migrate
docker compose up -d app
scripts/deployment_smoke.sh
```

`migrate` 是维护 profile，不属于常驻服务；默认拓扑始终只有 `app` 和 `db`。
