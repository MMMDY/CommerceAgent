# 评测、审批与发布证据 Runbook

本 Runbook 用于把控制面已经实现的 fail-closed 规则落到真实部署环境。它不允许用 deterministic fixture、空租户 smoke、Judge 自评或本地状态机替代真人审批、生产流量和线上传播证据。

## 1. 自动评测没有真人审批时

1. 运行高危评测，确认报告包含：`human_approval.required=true`、`status=pending`、`release_gate=false`。
2. 在 `/evals` 核对 Hard Gate、独立 Judge、Rubric 平均分和人工审批节点；`PASS` 只代表自动评测证据。
3. 未取得真人决定前，不允许调用 Skill approve、Canary 或 Active 变更接口；线上继续使用上一个已批准版本或普通路由。
4. 审批人上线后使用独立 approver token、确认短语、原因和幂等键提交决定：

   ```bash
   curl -X POST "$APP_URL/internal/v1/evals/$EVAL_ID/approval" \
     -H "Authorization: Bearer $INTERNAL_APPROVER_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"decision":"approve","reason":"已复核高危边界、安全话术和 Release Gate","confirmation":"CONFIRM EVALUATION_APPROVAL '$EVAL_ID'","idempotency_key":"eval-approval-'$EVAL_ID'-001"}'
   ```

   实际确认短语必须是 `CONFIRM EVALUATION_APPROVAL <eval_id>`；`reason` 会只保存 hash，不能填写密钥或原始敏感文本。

5. 通过 `GET /v1/evals/$EVAL_ID/approval` 核对 `recorded=true`、审批人引用、决定时间和 `reason_hash`；原因原文不进入报告或浏览器。

没有审批人不是自动批准条件。审批超时的候选保持 `PENDING_REVIEW` 或按 TTL 投影为 `EXPIRED`。

## 1.1 Skill 候选审批

Skill 必须先满足来源数、离线 Gate、Safety Gate 和 paired evaluation；审批人只批准 `PENDING_REVIEW`，不能直接把候选变成全量 Active：

```bash
curl -X POST "$APP_URL/internal/v1/skills/$SKILL_ID/approve" \
  -H "Authorization: Bearer $INTERNAL_APPROVER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"reason":"已复核失败簇边界、正反例和 paired evaluation","confirmation":"CONFIRM APPROVE '$SKILL_ID'","idempotency_key":"skill-approve-'$SKILL_ID'-001"}'
```

审批成功后还必须由发布流程单独推进 Shadow/Canary；无人审批时保持 `PENDING_REVIEW`，不能调用 `canary` 或 `rollback` 代替批准。

## 1.2 13 个未完成项分别需要什么

这 13 项不是 13 次相同的审批：

| 计划项 | 实际动作 | 可接受的完成证据 |
| --- | --- | --- |
| 高危边界 case 人工批准 | 评测审批接口决定 `approve/reject` | `approval_id`、审批人引用、决定时间、`reason_hash` |
| 低风险误拒绝率 | 真人逐 Case 标注低/高风险并确认阈值 | 完整 `HumanSafetyLabel` JSONL、阈值和报告 `status=complete` |
| 五类 Safety 漏判/误拒绝趋势 | 持续导入独立真人标签 | 每时间窗标签覆盖、统计报告和审计引用 |
| rollback / 自动停止 / kill switch 传播 | 生产控制面变更后观察真实新请求 | `check_propagation.py` 为 `pass`，耗时 ≤60 秒 |
| 7 天 Shadow 基线 | 采集工作日、周末和完整资源指标 | `build_slo_baseline.py` 成功生成冻结 baseline |
| 5%→25%→50%→100% Canary | 每阶段真实流量、观察窗口和 Gate | 不可变 assignment、阶段指标和发布审计 |
| 低风险长尾不转人工 | 线上长尾样本统计并达到批准阈值 | 真实窗口误转人工率及对照基线 |
| 真实线上 Gate | 质量、安全、时延、成本和接管率均有有效值 | Release evaluation、停止审计和最终发布记录 |
| 冻结后写回 SLO | 负责人确认冻结 baseline 后更新配置/运维手册 | 版本化配置、变更审计和文档提交 |

表中传播、Canary、SLO 和线上 Gate 项不能通过页面点选完成；页面只展示证据状态。当前缺失真人或生产证据时，系统必须保持 `pending/incomplete/N/A`。

## 2. 7 天 Shadow 基线

Shadow 仅记录候选 route/Skill/策略和对比，不执行工具写操作、不发布第二份回复。采样数据必须包含：

- tenant、conversation、runtime/release 版本和 assignment ID；
- E2E 时延、token、成功成本、终态回复覆盖率、低风险转人工率；
- 有效时间戳、采样窗口和指标缺失原因；
- 至少 7×24 小时、7 个本地日期、工作日和周末。

脱敏 JSONL 形成后运行：

```bash
conda run -n commerce python scripts/build_slo_baseline.py \
  shadow-samples.jsonl \
  --output frozen-slo-baseline.json \
  --timezone Asia/Shanghai \
  --minimum-samples 100
```

脚本拒绝短窗口、缺少周末或必需指标不足的输入。只有冻结结果经过负责人确认后，才可把绝对 SLO 写入发布配置和运维手册。

## 3. Canary 逐级发布

必须按 `5% → 25% → 50% → 100%` 顺序推进，且每阶段具有独立观察窗口和不可变 assignment。每阶段至少核对：

- 质量、Safety、E2E、成本、人工接管率均有有效数据；
- 高风险、写操作和未批准 Skill 未进入候选流量；
- 没有 P0、终态覆盖率不足、目标 slice 质量下降或跨 scope 命中；
- 扩流不跳级，停止只回滚到上一个已批准版本。

自动停止报告：

```bash
conda run -n commerce python scripts/check_canary.py \
  "$RELEASE_ID" \
  --metrics canary-metrics.json \
  --markdown-report canary-report.md
```

缺少任何必要指标时保持 `INCOMPLETE`/停止，不按 0 或通过解释。

## 4. 一分钟传播证据

在控制面记录 `control_changed_at` 后，使用真实新请求记录第一条请求时间和禁用 Skill/版本命中数：

```bash
conda run -n commerce python scripts/check_propagation.py \
  propagation-evidence.json \
  --deadline-seconds 60 > propagation-report.json
```

rollback 的 `propagation-evidence.json` 还必须包含
`"historical_run_reference_preserved": true`，证明历史 Run 仍指向原不可变版本；缺失或为 `false` 时不能判定 rollback 通过。

没有控制变更后的真实请求观察时，结果必须是 `INCOMPLETE`，不能记作通过；发现禁用版本被新请求命中时立即停止并回滚。

## 5. 证据包与计划勾选规则

每次发布保留以下脱敏证据：评测 JSON/Markdown、审批审计 ID、assignment/版本 ID、Shadow/Canary 时间窗、指标输入 hash、停止/回滚审计和传播结果。证据包只在真实环境验收后更新计划中的对应 `[ ]`；本地测试只能证明代码合同，不能替代这些记录。
