# Skill Kill Switch 与回滚边界证据

日期：2026-09-18

## 实现

- migration `20260918_0024` 新增 tenant 级 `experience.skill_controls`，保存启停状态、操作人、原因 hash 和更新时间；当前 head `20260918_0025` 另增加 release assignment comparison 的最小更新权限。
- `GET /internal/v1/skills/kill-switch` 使用 admin 认证并返回脱敏状态/权限标识；`POST` 使用独立 approver 认证、确认短语、持久化幂等和审计事件；普通 admin 不显示变更操作入口。
- 每个运行请求在 Skill Registry 检索前读取该租户开关；关闭时跳过 Skill 命中，历史 Skill 版本和 `skill_matches` 不删除。
- 控制表读取失败时 fail closed，只回退普通路由，不阻断 Safety Router，也不扩大业务能力。
- 现有 TTL 查询和 `ROLLED_BACK` 版本过滤继续保留；Skill rollback 不删除历史版本/匹配记录。

## 验证

```text
ruff check src tests                PASS
mypy src                            PASS
隔离 PostgreSQL contract            49 passed
Python 全量（隔离 PostgreSQL）       435 passed, 2 skipped
前端 lint/typecheck/Vitest/build    PASS；Vitest 10 passed
bundle/license 检查                 PASS
```

contract 测试已验证 tenant 开关隔离与可恢复、只读控制状态投影、TTL 到期和 rollback 历史保留；这些是数据库/代码契约，不等于线上一分钟生效测量。线上传播时延仍未宣称完成。
