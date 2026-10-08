# Phase N7 Demo Runtime 验证记录

日期：2026-09-19

## 结果

| 检查 | 结果 |
| --- | --- |
| demo PostgreSQL `alembic_version` | `20260918_0025` |
| app 镜像 | 基于当前工作区重建成功，包含最新后端迁移与前端产物；镜像 digest `sha256:b57f2a0decd3c9befe03d92e0265ffb0c42a1789a5f922b23021569d195eb912` |
| `GET /health/ready` | HTTP 200，`{"status":"ready"}` |
| `GET /` | 返回最新前端入口及 `index-VUuGCcEu.js` / `index-CFkUr69F.css` |
| `GET /v1/evals/baseline-20260918/markdown` | HTTP 200，返回带附件名的 Markdown，包含平均分和时延/Token/成本表 |
| `scripts/release_smoke.sh` | 通过 |

## 构建修复

- Python 默认构建源改为可配置且默认使用 `https://pypi.org/simple`；原默认镜像在 Docker builder 网络中超时。
- 前端 `package-lock.json` 的 275 个固定下载地址从不可达的腾讯镜像切换到 `https://registry.npmjs.org`，未改变依赖版本。
- 构建验证使用 `docker build --network=host`；部署环境仍应按其网络策略配置 `PIP_INDEX_URL`，不能把本机网络结果视为生产可用性证明。

## 边界

本记录只证明本地 demo 数据库、最新容器和健康检查一致；不证明真人审批、生产流量、真实 Canary、线上传播时延或 7 天 Shadow 基线。
