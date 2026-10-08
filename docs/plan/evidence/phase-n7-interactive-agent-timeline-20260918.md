# Phase N7 交互式 Agent 流程时间轴证据

日期：2026-09-18

## 本次改进

- 对话工作台主流程节点增加白名单事件证据摘要：节点状态之外显示该节点关联事件数和最新事件号；没有事件时显示“暂无事件证据”。
- Agent 事件时间轴支持按“全部、受理、识别与路由、Agent 执行、Guardrail、上线与成本、回复发布”筛选，筛选结果仍只展示最近 12 条脱敏事件。
- 事件卡展示服务端事件时间戳和相邻事件的实际间隔；缺少或异常时间戳时不推断时延。
- 保留原有敏感字段边界：Prompt、思维链、工具参数、原始模型输入输出和未脱敏纠错文本不进入前端。
- 保持桌面端横向流程和窄屏端纵向流程；阶段筛选按钮具备键盘焦点和 `aria-pressed` 状态。

## 验证

在 `apps/web` 执行：

```text
npm run lint              PASS
npm run typecheck         PASS
npm test -- --run         PASS: 4 files / 10 tests
npm run build             PASS
npm run bundle:check      PASS: Apache-2.0, 803817 JavaScript bytes
```

## 边界

以上证据证明前端投影、类型、测试和生产构建可用；不证明线上 SSE 延迟、真实 Agent 流量覆盖或后端事件写入完整性。后端事件缺失时页面明确显示无事件证据，不以 UI 状态替代后端事实。
