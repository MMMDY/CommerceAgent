# Phase N7 前端 Skill 生命周期流程证据

日期：2026-09-19

## 实现

- `/skills/:id` 新增可视化生命周期：失败簇证据 → 离线/Safety Gate → Paired Eval/Judge → 真人审批 → Shadow/Canary/Active。
- 流程节点由服务端 Skill 状态、独立来源数、Gate、paired evaluation 聚合结果和明确 `release_ids` 投影，未审批候选停在“等待审批”，不会显示为已上线。
- `REJECTED`、`EXPIRED`、`ROLLED_BACK` 和未达到来源/Gate 门槛的节点使用阻断状态；缺少评测结果使用待处理状态，不推断为通过。
- 未知、拒绝、过期和回滚状态不会复用“已通过审批边界”文案；新增 `EvolutionLifecycle.test.ts` 覆盖待审批、已关联发布、阻断和未知状态四类路径。

## 验证

在 `apps/web` 执行：

```text
npm test -- --run: 8 files / 24 tests passed
npm run typecheck: passed
npm run lint: passed
npm run build: passed
npm run bundle:check: passed (Apache-2.0, 851794 bytes)
```

## 边界

- 页面只把后端明确返回的 `release_ids` 解释为 Release 关联；Skill 状态本身不会被猜测成 Canary。
- 本地测试证明状态投影和阻断显示，不证明真实人工审批、线上流量或生产传播时延。
