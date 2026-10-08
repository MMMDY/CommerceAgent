# Phase N7 前端状态覆盖审计证据

日期：2026-09-19

## 本轮修正

- Skill 详情的 Release 关联次级接口增加独立 loading 状态；请求尚未完成时显示“加载中”，不会先显示 `N/A`。
- 该接口仍区分 403、其他失败和成功但无关联三种结果；成功无关联才显示 empty/N/A。
- Skill 状态投影同时覆盖已批准、待审批、阻断和未知状态，未知状态保持中性，不使用成功色。

## 状态覆盖矩阵

| 页面/区域 | Loading | Empty | Partial/Error/403 | 断流或未知状态 |
| --- | --- | --- | --- | --- |
| 对话与 SSE | 会话、Run、人工审核 | 空消息 | 会话错误、人工审核重试 | SSE 断流轮询回退；Run/事件未知状态中性 |
| Run Trace | 主数据、事件、RAG、关系 | 无 Run/无事件 | 子接口 partial、403 | StatusTag 与时间戳缺失均不推断 |
| 评测 | 报告、Dashboard、Case、审批、详情 | 无批次/无 Case | Dashboard、Case、审批 partial/403 | Gate/Judge/审批缺失保持 N/A/pending |
| 运营 | 摘要、Safety 审计、学习链路、Release | 无运营/无趋势 | 主接口和次级接口 partial/403/快照 | Release/Run 状态未知中性 |
| 失败、Skill、Release | 主接口及 Release 关联 | 无样本/无 Skill/无 Release | 操作、控制开关和关联接口 partial/403 | 生命周期未知/失败不显示成功语义 |

## 验证

```text
PYTHONPATH=. conda run -n commerce pytest -q: 406 passed, 63 skipped
apps/web: npm test -- --run: 8 files / 24 tests passed
apps/web: npm run typecheck: passed
apps/web: npm run lint: passed
apps/web: npm run build: passed
apps/web: npm run bundle:check: passed (Apache-2.0, 851794 bytes)
git diff --check: passed
```

## 边界

- PostgreSQL contract、真实人工审批、线上流量和生产传播时延仍不由本地状态测试替代。
- 表格中的“覆盖”表示代码路径有显式状态投影；不代表接口在生产环境一定返回真实数据。
