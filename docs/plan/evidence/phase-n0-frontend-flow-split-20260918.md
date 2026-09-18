# Phase N0 前端流程可视化与基础拆分证据

## 已实现

- `App.tsx` 复用统一 `contracts.ts` 类型和 `api/client.ts` 请求错误边界，避免页面重复定义运行时合同。
- 事件时间轴抽为 `components/EventTimeline.tsx`，对话页和右侧 Trace 共用事件标签、阶段归类和安全字段投影。
- Agent 流程可视化继续覆盖受理、Safety/Domain/Intent/Policy、编排、Guardrail、回复，以及 RAG、工具、Skill、兜底分支；敏感 Prompt、思维链和工具参数不进入页面。
- 前端已有的评测、运营、失败归因、Skill 和发布页面继续由独立控制面组件承载，路由保持兼容。

## 验证

```text
npm run lint: passed
npm run typecheck: passed
npm test -- --run: 3 test files, 7 tests passed
npm run build: passed
npm run bundle:check: passed (Apache-2.0, 786297 bytes)
```

## 边界

这次拆分只证明前端模块边界和确定性流程投影可构建、可测试；不代表真实线上流量、真人审批或 Live E2E 能力已完成。
