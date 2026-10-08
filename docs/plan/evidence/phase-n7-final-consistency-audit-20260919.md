# Phase N7 实现、迁移、测试与证据一致性审计

日期：2026-09-19

## 审计结论

当前代码实施清单中的本地可验证项与实现、迁移、测试和最新证据一致；计划中依赖真实人工/生产外部事实的项目仍保持 `[ ]`，没有用 deterministic fixture、demo smoke 或本地状态机替代。

## 当前事实

| 项目 | 当前证据 |
| --- | --- |
| 迁移 head | `src/db.py` 的 `EXPECTED_ALEMBIC_REVISION=20260918_0025`；demo PostgreSQL `alembic_version=20260918_0025` |
| Python 回归 | `PYTHONPATH=. conda run -n commerce pytest -q`：`406 passed, 63 skipped`；跳过项为未配置的 PostgreSQL/Live Model 条件 |
| 隔离 PostgreSQL | 当前 migration chain：`459 passed, 2 skipped`；contract/recovery 不再因缺少数据库跳过 |
| 前端回归 | Vitest `8 files / 24 tests passed`，typecheck、lint、production build 通过 |
| Bundle/license | `npm run bundle:check`：Apache-2.0，JavaScript `851794` bytes |
| Runtime | `GET /health/ready` HTTP 200；`GET /` 返回 `index-VUuGCcEu.js`；`release_smoke.sh` 通过 |
| 评测报告 | 历史命名报告可读取 Dashboard、Case、审批和 Markdown；缺失 usage/价格/Judge 保持 `N/A` |

## 审计范围

- 计划引用的 `src/`、`apps/`、`tests/`、`scripts/` 和 `docs/` 证据路径均存在。
- README、计划文件、`src/db.py`、Alembic 最新 revision 和 demo 数据库 head 一致。
- Run ↔ Eval/Failure、Case → Failure、Skill → Release 的关系使用后端明确 ID 和 tenant 边界；Dashboard 与 Markdown 使用同一报告聚合合同。
- 历史证据中的旧 bundle 字节数、测试数量和旧 migration 版本保留为历史记录，不被重新解释为当前状态。

## 不在本审计结论内

真人审批记录、人工安全标签、7 天 Shadow 基线、真实 `5% → 25% → 50% → 100%` Canary、生产一分钟传播、真实线上质量/安全/时延/成本 Gate 仍需部署环境或人工外部证据。
