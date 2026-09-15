# CommerceAgent internal-beta-20260916-r3

状态：`internal beta / mock business data`

候选源码 commit：`bd0cb5533f2f0f78a37123af780e104724948a0d`
数据集 SHA-256：`240846bdb3d3dbb0b5c2b16df9df4b9d8f45a24c06bd8b77abd84910edb10ff5`
Rubric SHA-256：`c11dbb3371f0fb31bbe01df8ed74c10238b620b3840cf1e998eb9febc9a42ceb`
评测报告：`evals/reports/release-20260916-judge-chat-v3/report.json`

Release 评测结果：`status=completed`、`release_gate=true`、`self_judged=false`；300 case × 3 次共 900 attempts，hard pass `300/300`，最终通过 `296/300`，三次全通过率 `0.9867`，30-case Judge 校准一致率 `1.0`。Judge 模型仅记录为 `deepseek-chat`，不包含凭据。

本摘要只记录可脱敏的版本指纹，不包含 API key、数据库 URL、Judge prompt 或原始 payload。
正式 Release gate 需额外通过 `scripts/release_check.py`：独立 Judge、30 条校准一致率至少 90%、300 case 三次运行完整、24 小时 soak 完成。

当前 `release_check.py --require-clean` 已通过；24 小时 soak 尚未运行，因此该产物仍标记为 internal beta，不代表生产可用。
