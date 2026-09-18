# Phase N7 当前工作区验证记录

日期：2026-09-18

## 本地可复现验证

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| Python 回归 | `PYTHONPATH=. conda run -n commerce pytest -q` | `381 passed, 63 skipped` |
| Python lint | `conda run -n commerce python -m ruff check src tests` | 通过 |
| Python 类型 | `conda run -n commerce python -m mypy src` | 通过，142 source files |
| 前端类型 | `npm run typecheck` | 通过 |
| 前端 lint | `npm run lint` | 通过 |
| 前端测试 | `npm test -- --run` | 5 files / 13 tests passed |
| 前端构建 | `npm run build` | 通过；Vite 仅提示 chunk 大于 500 kB |
| Bundle/license | `npm run bundle:check` | 通过；Apache-2.0；JavaScript 816078 bytes |

## 未宣称完成的外部证据

- PostgreSQL contract/recovery 测试因当前 shell 未提供 `DATABASE_TEST_URL` 而跳过；
- live model 测试因未显式设置 `RUN_LIVE_MODEL_TEST=1` 而跳过；
- 真人审批、真实 5% → 25% → 50% → 100% Canary、生产传播时延和 7 天工作日/周末基线没有本地替代证据，计划中的对应 checkbox 保持 `[ ]`；
- 严格执行 `ruff check src tests scripts` 仍包含仓库历史脚本格式问题，本轮只将 `src tests` 结果记为通过。

## 前端展示范围

对话、Run、评测、运营、失败、Skill 和 Release 页面均有结构化流程投影；页面只展示白名单决策、状态、指标、事件和脱敏证据，不展示 Prompt、思维链、工具参数、密钥或未授权纠错文本。未知状态使用中性状态标签，不显示为成功。
