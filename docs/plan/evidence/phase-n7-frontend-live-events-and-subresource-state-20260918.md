# Phase N7 前端实时事件与次级数据状态证据

日期：2026-09-18

## 本轮实现

- 对话页 SSE 订阅补齐后端 `EventType` 已定义但此前遗漏的事件：人工工单创建、回复发布失败、操作预览、用户确认、提交开始/结果、状态校验和业务状态不确定；同时保留 RAG 失败流程投影事件的兼容展示。
- 事件时间轴为 RAG 失败、回复发布失败和业务状态不确定使用危险语义，并对实际事件提供中文可读标签；不展示 Prompt、工具参数或隐藏推理。
- 统一状态投影新增 `created`、`routing`、`running_readonly`、`running_workflow`、`committing` 和 `verifying` 等运行中状态，统一显示为警告/进行中，不会与成功状态混淆。
- `/operations` 对 Safety 审计、失败学习和 Release 次级接口增加独立 loading、403、partial 和刷新失败状态；主聚合刷新时保留最近一次成功快照并显式说明，不把尚未返回的空数组解释为“没有数据”。
- Run 详情从 `release_assigned` / `skill_matched` 的真实事件中提取明确关联 ID，Release assignment 从后端 comparison 投影展示 Skill 下钻；没有明确 ID 时显示 `N/A`。
- Skill 详情可按持久化 `cluster_key` 回到服务端过滤的失败样本池；失败样本和聚合趋势共用服务端过滤条件，过滤条件作为白名单查询参数传递，不在浏览器端拼接或猜测失败关系。

## 验证

```text
npm --prefix apps/web run typecheck       PASS
npm --prefix apps/web test -- --run       6 files / 16 tests passed
npm --prefix apps/web run lint            PASS
npm --prefix apps/web run build           PASS
npm --prefix apps/web run bundle:check    PASS；Apache-2.0；825564 JavaScript bytes
git diff --check                           PASS
PYTHONPATH=. conda run -n commerce pytest -q  PASS；406 passed, 63 skipped
conda run -n commerce python -m mypy src apps/api/main.py  PASS；146 source files
```

新增状态回归断言：`running_workflow`、`routing` 为 warning，且状态标签分别投影为“流程执行中”；未知后端状态仍为 neutral。

## 边界

本证据只证明前端能够接收和展示真实事件合同，并正确区分次级接口状态；不证明生产环境一定产生这些事件，也不证明真实 Canary、传播时延、真人审批或七天线上基线已经完成。
