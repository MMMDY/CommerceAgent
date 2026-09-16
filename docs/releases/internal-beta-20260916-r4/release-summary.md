# CommerceAgent internal-beta-20260916-r4

状态：`internal beta / mock business data`

候选源码 commit：`9efde6e1d84b4a42fd460f6958a50c72a883c3c9`
数据集 SHA-256：`240846bdb3d3dbb0b5c2b16df9df4b9d8f45a24c06bd8b77abd84910edb10ff5`
Rubric SHA-256：`c11dbb3371f0fb31bbe01df8ed74c10238b620b3840cf1e998eb9febc9a42ceb`
评测报告：`evals/reports/release-20260916-bounded-judge-v2/report.json`

Release 评测结果：`status=completed`、`release_gate=true`、`self_judged=false`；300 case × 3 次共 900 attempts，hard pass `300/300`，最终通过 `296/300`，三次全通过率 `0.9867`，30-case Judge 校准一致率 `1.0`。Judge 模型仅记录为 `deepseek-chat`，不包含凭据。

Release gate 已通过 `scripts/release_check.py --require-clean` 与 bounded soak 校验。bounded soak 报告为 `evals/reports/release-soak-bounded.json`：20 个样本、613 秒、错误数为 0。该证据用于验证资源采集和短时稳定性，不代表生产环境的长期稳定性保证；不设置连续 24 小时运行测试。
