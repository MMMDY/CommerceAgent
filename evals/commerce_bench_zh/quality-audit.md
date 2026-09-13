# 300-case 语义质量审核

审核日期：2026-09-13。冻结对象：`cases.jsonl` 与 `knowledge.jsonl`。

本审核逐条遍历全部 300 个 case（唯一 ID、track、期望字段和安全约束），不以 JSON 可解析性替代语义合同。可复验命令：

```bash
python -m pytest tests/harness/test_dataset_contract.py
```

| 轨道 | 数量 | 逐项审核规则 | 结论 |
|---|---:|---|---|
| intent/route | 150 | 每项均有 intent、route、tool 金标 | 通过 |
| workflow | 60 | 每项均有动作、工具、参数/缺槽、确认要求 | 通过 |
| RAG | 50 | 每项均有事实、引用 ID，且引用属于 13 条冻结知识证据 | 通过 |
| clarification | 20 | 每项均要求澄清、缺失槽和可接受关键词 | 通过 |
| guardrail | 20 | 每项均有 outcome、reason code；并至少含 forbidden tool 或不得虚假声称成功约束 | 通过 |

本次冻结 hash：`cases.jsonl` 为 `240846bdb3d3dbb0b5c2b16df9df4b9d8f45a24c06bd8b77abd84910edb10ff5`；`knowledge.jsonl` 为 `bb86344cd7a2c39d19abd5d8352dd479caf4a15bc3956696c6fa340cdad88ac4`。本次修订为 5 条原本缺少 forbidden tool 的 guardrail case 补充最小禁止调用约束；未改变用户消息、预期 route/outcome 或知识证据。

任何 case、ID、track、证据引用或金标字段的改动都会使上述合同测试或 loader hash 发生变化，必须重新审核并单独提交数据变更。
