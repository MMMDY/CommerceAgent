# Phase N7 失败学习链路证据（2026-09-18）

## 本次交付

运营总览新增服务端驱动的失败学习链路：

```text
异常指标 → 失败簇 → 归因复核 → Skill 候选 → Canary → 停止/回滚
```

- `GET /internal/v1/operations/learning-summary` 由 `FailureRepository.learning_summary()` 生成租户隔离的白名单 DTO。
- 失败簇、最新归因、Skill 候选和 Release 状态均由 PostgreSQL 持久化记录关联；浏览器不再用多个页面结果自行拼接链路。
- Skill 生成门槛使用独立 `case_id/run_id/failure_id` evidence identity 统计，而不是把单个 case 的 `source_count` 当成跨来源数量。
- Release 只有在 `candidate_version` 或 assignment comparison 明确记录不可变 Skill ID/版本 ID 时才建立关联；没有审计证据时前端显示“暂无可证明关联”。
- 运营页新增六阶段流程图和 cluster 下钻表，入口可到失败详情、Skill 详情和 Release 详情；不返回 Prompt、原始回复、思维链或纠错原文。

## 验证

| 检查 | 结果 |
|---|---|
| `conda run -n commerce python -m ruff check src tests` | 通过 |
| `conda run -n commerce python -m mypy src` | 通过 |
| `conda run -n commerce python -m pytest -q`（未注入 `DATABASE_TEST_URL`） | `377 passed, 62 skipped` |
| `./scripts/run_phase1_contract_tests.sh` | `51 passed` |
| `npm run typecheck && npm run lint && npm test -- --run` | `10 passed` |
| `npm run build && npm run bundle:check` | 通过；`809053` JS bytes，Apache-2.0 license 通过 |

PostgreSQL contract 额外验证：

- 空租户不会生成 Skill 或 Release 的伪关联；
- 5 个独立脱敏 evidence 能通过真实数据库读取关联到 Skill 候选；
- 以 Skill 不可变 ID 作为候选版本的 Release 能被下钻展示；
- 查询结果不包含 `summary_redacted`。

## 边界与未完成项

- 这证明的是控制面数据链路和可视化，不证明真实线上流量已经经过 Shadow/Canary。
- 没有 assignment comparison 或不可变版本关联时，不会把“有一个发布记录”显示为该失败簇已 Canary。
- 真实 7 天基线、线上自动停止后一分钟内传播和一分钟内前端刷新仍保持未完成。
