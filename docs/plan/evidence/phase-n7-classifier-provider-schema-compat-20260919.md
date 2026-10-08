# Phase N7 供应商分类响应兼容与订单物流闭环证据

> 日期：2026-09-19  
> 范围：分类模型 provider response normalization、只读订单/物流复合查询

## 根因

主 Agent 与分类 Agent 使用同一 OpenAI-compatible API 配置，HTTP 请求均能成功。分类模型返回的字段词汇与项目内部合同不同：

- `domain: ecommerce`，内部合同要求 `commerce`；
- `risk_hint: low`，内部路由合同要求 `read_only/write/unknown`；
- `alternatives` 为带 `intent/confidence` 的对象数组，内部合同要求字符串数组。

旧实现直接执行 `IntentClassification.model_validate_json()`，导致分类解析失败，统一进入 `CLASSIFIER_UNAVAILABLE` 人工兜底。该路径不是高风险判定。

## 修复

- `src/models/gateway.py` 在不可信 provider 边界增加白名单归一化：`ecommerce → commerce`、`low → read_only`、对象 alternatives → intent 字符串；未知 domain/risk 枚举保守降级为 `unknown`。
- 分类 Prompt 明确要求 `risk_hint` 合同值。
- `get_delivery_tracking` 的模型可见输入收紧为仅 `order_id`；`tracking_id` 仅作为输出。
- 对复合只读查询，如果模型把可信观察中的 `tracking_id` 错当输入，代码仅使用同一 Run 已验证的订单查询结果绑定原始 `order_id`，不放宽 owner/tenant/tool allowlist。
- 修正决策错误码映射，使缺少/非法工具参数报告为 `INVALID_TOOL_ARGUMENT`，与 `TOOL_NOT_ALLOWED` 区分。

## 验证

- 分类单测：`10 passed`。
- 针对性回归：`29 passed`。
- 全量 Python 回归：`407 passed, 63 skipped`；跳过项为需显式 PostgreSQL 或 live 开关的测试。
- 真实分类网关请求（订单 `ORD-DEMO-001`）：返回 `track_order / read_only / commerce / low / confidence=0.95`，未触发 repair。
- 重建 Demo 镜像并通过 `127.0.0.1:19473` 发起真实请求，Run `f81f21ae-f8d4-4253-b9d8-2e4328d7bd2c`：
  - 分类成功并路由 `track_order → order_query`；
  - `get_order_status` 与 `get_delivery_tracking` 均成功；
  - 最终 Run `completed`，无 `CLASSIFIER_UNAVAILABLE`、无 `HANDOFF_CREATED`；
  - 前端可见回复同时包含订单状态、物流单号和预计送达日期。

