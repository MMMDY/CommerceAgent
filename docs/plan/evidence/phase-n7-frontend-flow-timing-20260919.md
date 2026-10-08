# Phase N7 前端 Agent 节点级时延可视化证据

日期：2026-09-19

## 实现

- 对话页 `AgentFlow` 在主链路节点上展示真实事件数和阶段可测时延：受理、识别与路由、策略、Agent 执行、Guardrail、回复发布。
- 流程卡标题展示整个事件时间包络；阶段或整体缺少至少两个有效时间戳时显示 `N/A`，不根据轮询间隔、渲染时间或事件数量推断时延。
- 终态 Run 不再自动把缺少事件证据的节点标记为完成；早期失败只标记已有证据的节点，缺失节点显示“未使用 / 无事件证据”或待处理。
- 受理节点同样要求 `run_created` 事件证据；仅有终态状态而没有事件链时显示“未使用 / 无事件证据”，不把状态字段当作受理事实。
- 继续保留 RAG、Tool、Skill、Fallback 分支，以及 Safety / Intent / Policy 决策证据卡；该增量只增加白名单事件的可观测摘要，不增加 Prompt、思维链、工具参数或原始文本。
- 新增 `AgentFlow.test.ts`，覆盖有效时间戳的毫秒/秒格式化、缺失/非法时间戳的 `N/A` 边界，以及终态无事件和完整事件链的节点状态投影。

## 验证

在 `apps/web` 执行：

```text
npm test -- --run: 8 files / 24 tests passed
npm run typecheck: passed
npm run lint: passed
npm run build: passed
npm run bundle:check: passed (Apache-2.0, 851794 bytes)
```

当前 production bundle 入口为 `index-VUuGCcEu.js`；本地 demo 容器已重建并加载该入口。

## 边界

- 节点时延是前端对后端事件时间戳的白名单投影，不替代服务端 E2E、模型 TTFT 或生产 SLO 统计。
- 同一阶段只有一个事件时无法证明持续时长，页面显示 `N/A`；跨事件时间戳异常或倒序时不显示负时延。
- 本地构建和单测不证明真实线上流量、Canary、生产传播或质量收益。
