# CommerceAgent internal-beta-20260916-r3（历史证据，已由 r4 替代）

状态：`internal beta / mock business data`

候选源码 commit：`bd0cb5533f2f0f78a37123af780e104724948a0d`
数据集 SHA-256：`240846bdb3d3dbb0b5c2b16df9df4b9d8f45a24c06bd8b77abd84910edb10ff5`
Rubric SHA-256：`c11dbb3371f0fb31bbe01df8ed74c10238b620b3840cf1e998eb9febc9a42ceb`
评测报告：`evals/reports/release-20260916-judge-chat-v3/report.json`

Release 评测结果：`status=completed`、`release_gate=true`、`self_judged=false`；300 case × 3 次共 900 attempts，hard pass `300/300`，最终通过 `296/300`，三次全通过率 `0.9867`，30-case Judge 校准一致率 `1.0`。Judge 模型仅记录为 `deepseek-chat`，不包含凭据。

本摘要只记录可脱敏的版本指纹，不包含 API key、数据库 URL、Judge prompt 或原始 payload。
正式 Release gate 需额外通过 `scripts/release_check.py`：独立 Judge、30 条校准一致率至少 90%、300 case 三次运行完整，以及 bounded soak 报告校验通过。

原候选的 `release_check.py --require-clean` 已通过；该 r3 证据包已由重新冻结的 r4 候选替代，当前有效证据见 `docs/releases/internal-beta-20260916-r4/`。

当前采用 10 分钟 bounded soak：`release-soak-bounded.json`，采样间隔 30 秒，后台 PID 由同名 `.pid` 文件管理。实际结果为 `status=completed`、20 个样本、613 秒、错误数为 0，并已通过 `scripts/verify_soak_report.py`。该证据用于验证资源采集和短时稳定性，不代表生产环境的长期稳定性保证；不设置连续 24 小时运行测试。
