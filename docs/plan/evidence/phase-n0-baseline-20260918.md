# Phase N0 基线证据

生成日期：2026-09-18（Asia/Shanghai）  
源码基线：`347f2e63d72c7f47c4477184853410cb18126b4d`（当前工作区为 dirty，报告明确记录生成时状态）

## 评测基线

报告：`evals/reports/baseline-20260918/report.json`  
Markdown：`evals/reports/baseline-20260918/report.md`

| 字段 | 值 |
|---|---|
| `schema_version` | `2.0` |
| `runtime` | `deterministic_fixture` |
| `status` | `completed` |
| `selected_cases` | `300` |
| `passed_cases` | `300` |
| dataset hash | `240846bdb3d3dbb0b5c2b16df9df4b9d8f45a24c06bd8b77abd84910edb10ff5` |
| rubric hash | `sha256:c11dbb3371f0fb31bbe01df8ed74c10238b620b3840cf1e998eb9febc9a42ceb` |
| runtime hash | `56a7d9edae15510bbe15d0f52bcac6f549126b7078efbfdef8307acb482f8c8e` |
| prompt hash | `sha256:commerce-agent-deterministic-runtime-prompt-v1` |

该结果只代表 deterministic fixture 的可复现合同回归，不代表真实模型成功率，也不代表真实 RAG 或线上流量能力。

## 验证矩阵

| 范围 | 命令 | 结果 |
|---|---|---|
| Python 全量（包含 deployment/unit/harness） | `PYTHONPATH=. ./.venv/bin/pytest -q` | `325 passed, 50 skipped` |
| PostgreSQL contract | `./scripts/run_phase1_contract_tests.sh` | `39 passed` |
| PostgreSQL recovery（隔离 contract DB） | `PYTHONPATH=. ./.venv/bin/pytest -q tests/recovery` | `17 passed` |
| 前端 lint/typecheck/test/build | 在 `apps/web` 执行 `npm run lint && npm run typecheck && npm test -- --run && npm run build` | 全部通过，Vitest `3 passed` |
| Python 静态检查 | `ruff check`、`mypy src apps/api/main.py` | 通过 |

说明：外部 Live Model 测试未在该基线中调用；未配置 Live Model 的项目仍按 `skip/incomplete` 处理，不能回填为通过。
