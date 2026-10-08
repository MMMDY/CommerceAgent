# 低置信度长尾请求状态修复证据

> 日期：2026-09-19

## 复现

输入：`我今天心情不好，该买什么东西`

分类器返回了 `product_information`，置信度 `0.55`。路由器正确判断为 `LOW_CLASSIFICATION_CONFIDENCE`，本应等待用户补充信息，但 Run 被包装成 `UNEXPECTED_EXECUTION_ERROR`。

## 根因

数据库约束 `ck_agent_runs_dual_executor_shape` 只允许未选择执行器的 Run 处于 `created/routing/waiting_human/...`，没有允许 `waiting_user`。而低置信度分类属于执行器选择前的澄清状态，写入 `waiting_user` 时触发 PostgreSQL check constraint。

## 修复

- 新增 migration `20260919_0026_pre_route_waiting_user`，允许无 executor 的 Run 进入 `waiting_user`。
- 增加 PostgreSQL contract：低置信度 pre-route 请求进入 `waiting_user`，且不绑定任何 executor/workflow。

## 验证

当前 Demo 已迁移并重启。再次输入同样话术后：

- Run 状态：`waiting_user`
- 当前步骤：`clarify`
- 原因：`LOW_CLASSIFICATION_CONFIDENCE`
- 事件包含 `waiting_for_user`
- 前端收到正常澄清回复：`我还不确定你的具体需求，可以补充一下你想查询或办理的事项吗？`
- 不再出现 `UNEXPECTED_EXECUTION_ERROR`。

