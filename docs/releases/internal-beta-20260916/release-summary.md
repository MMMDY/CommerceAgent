# CommerceAgent internal beta（2026-09-16）

状态：`partial / blocked`。这是使用 mock business data 的内部候选，不是生产版本。

已完成的证据提交：

- Phase 5 hard gate：`1edaf7a`
- Phase 6 运维与安全切片：`39479fd`、`36d04a7`
- 当前候选源码 commit：以 `git rev-parse HEAD` 为准（生成证据时必须保持 clean worktree）。

已验证：全量 Python `208 passed, 42 skipped`，前端测试/构建通过，300 case deterministic 三次运行 `900 attempts / 300 hard pass / 300 final pass`，Compose migration `20260916_0011`，备份及空库恢复演练通过，live/ready 通过。

尚不能宣称 Release gate 通过：当前 Judge 与候选 Agent 使用相同 profile（只能 `self_judged/provisional`），30-case 独立校准一致率、独立 Judge 的三次 release run 和 24 小时 soak 尚未满足。使用 `scripts/release_check.py` 会对此 fail closed。
