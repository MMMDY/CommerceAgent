# CommerceAgent 下一代 Agent 阶段性代码改进计划

> 版本：v1.0  
> 日期：2026-09-18  
> 状态：`in_progress`  
> 上位方案：[下一代 Agent 持续改进实施方案](./next-generation-agent-continuous-improvement-plan.md)  
> 决策状态：D1～D10 全部采用上位方案推荐默认值  
> 当前数据库 migration head：`20260918_0025`

## 本轮已落地的代码证据（2026-09-17）

本轮已将控制面从静态规划推进为可运行的垂直切片：

- 数据库已升级到 `20260918_0025`，新增 `feedback`、`experience`、`release` 三个 schema，并加入失败复核字段、Skill 定义不可变约束、发布 assignment、候选运行时注册、合并失败信号、纠错文本清理索引、Skill JSON/全局作用域约束、tenant 级 Skill kill switch 和 assignment comparison 的最小更新权限；`/health/ready` 会校验该 head。
- `POST /v1/runs/{run_id}/feedback` 支持 owner 点赞/点踩、幂等键、显式纠错授权和 30 天脱敏保留；失败 Run 会自动投影到失败样本池。
- `/internal/v1/failures`、`/reanalyze`、`/skills`、`/releases` API 已接入租户边界；生产必须配置 `INTERNAL_ADMIN_TOKEN` Bearer，demo 无 token 时只用于本地演示。
- Skill 候选要求至少 5 个来源且通过离线/安全 Gate；生命周期强制 `CANDIDATE → PENDING_REVIEW → 人工批准 → CANARY`，自动评测不能越级激活。
- 前端 `/runs/:id`、`/operations`、`/evals`、`/failures`、`/skills`、`/releases` 均展示结构化流程、Gate、时延、Token、成本、状态和空/错误态，不展示 Prompt、思维链、密钥或未脱敏文本。
- 前端增强（2026-09-17）：对话页增加受理→识别/路由→Agent 执行→Guardrail→回复发布的阶段事件计数；Run 详情增加真实事件路径、RAG 最终引用证据和风险→Domain→Intent→Policy→Executor 决策链；运营页增加线上 Agent 流程总览，并将侧栏 Trace 改为白名单结构化摘要。
- 前端可观测性修正（2026-09-17）：Run 详情将 `retrieve_knowledge`/`search_knowledge` 的真实调用时延单列为 RAG，普通业务工具单列；分类事件同时兼容 `routing` 与 `intent_classification` 标识；缺失时延/Token/成本统一显示 `N/A`，不附加误导性单位。
- 前端流程可视化补强（2026-09-17）：对话/运营页补充 RAG、模型、工具、失败学习分支和状态图例；评测页增加数据集→Hard Gate→Judge→Final Pass 质量漏斗；失败详情增加采集→聚类→归因→人工复核链路；发布详情按真实阶段显示完成、当前、待推进和停止状态，并展示候选流量进度。聚合接口没有提供的指标继续标记为“逐 Run 可追踪”或 `N/A`。
- 前端评测下钻补强（2026-09-18）：`/evals/:id` 增加 Track 筛选、Track × Rubric 平均分热力图、Judge 加权分数分布、按 Case 的重复 attempt 表，以及脱敏 JSON/Case CSV 导出；缺失 Judge 数据仍显示 `N/A`，不把重复运行高分折叠成稳定能力。新增 Case → Attempt → Judge → Trace 详情接口和页面流程卡，展示路由/意图、工具/RAG 证据引用、Judge 维度/证据摘要和最终判定，白名单投影不返回 Prompt、工具参数、原始回复或思维链。
- 前端流程证据补强（2026-09-18）：对话页 Agent Flow 增加 Safety/Intent/Policy 决策证据卡，展示风险/领域/策略、分类置信度、候选数、原因码、检测器版本和白名单事件号；评测热力图改读服务端 `evaluation_dashboard.judge_dimensions`，不再从浏览器 Case 行二次聚合。
- 对话事件流补强（2026-09-18）：SSE/回退轮询兼容 Skill 命中、发布 assignment、RAG、Guardrail 和安全兜底事件，并在阶段时间轴中归类展示；事件详情继续使用白名单字段，隐藏 Prompt、思维链和工具参数。
- 前端流程下钻补强（2026-09-18）：对话页主流程节点显示关联事件数/最新事件号；事件时间轴支持按受理、识别与路由、Agent 执行、Guardrail、上线与成本、回复发布筛选，并展示相邻真实事件时间间隔；缺失时间戳保持不推断。证据见 `docs/plan/evidence/phase-n7-interactive-agent-timeline-20260918.md`。
- 运营闭环补强（2026-09-18）：新增租户隔离的 `operations/learning-summary` 服务端投影，将异常指标、失败簇、独立 evidence 门槛、归因复核、Skill 生命周期和有明确不可变 ID/assignment 证据的 Canary/停止/回滚串成可下钻流程；前端没有后端关联时明确显示“暂无可证明关联”。证据见 `docs/plan/evidence/phase-n7-failure-learning-chain-20260918.md`。
- 前端状态与审批边界补强（2026-09-18）：Run 详情支持主数据与事件/RAG 次级数据的部分成功展示，403 明确显示无权限；评测页读取服务端 `human_approval` 投影并把 `pending` 停在真人审批节点；对话页展示 SSE 断流后的轮询回退；Release 列表/详情补齐 loading、403/error 和未知阶段的 partial 状态。失败/Skill 的完整部分接口与未知状态审计仍未完成。证据见 `docs/plan/evidence/phase-n7-frontend-state-and-approval-20260918.md`。
- 前端 Agent 生命周期图补强（2026-09-18）：控制面统一展示“在线请求链路”和“质量/学习链路”双泳道，失败样本增加脱敏 Run/Trace 下钻，对话页区分未检索、已检索未引用和有最终 RAG 证据；评测 Case 贯通真实运行时 `run_id` 到 Run Trace，旧报告缺失时不生成虚假链接。证据见 `docs/plan/evidence/phase-n7-frontend-lifecycle-map-20260918.md`。
- 前端状态投影补强（2026-09-18）：Run/Release 详情使用统一状态标签，未知、待处理、失败和成功状态采用不同视觉语义；新增状态投影单测，未知后端状态不会显示为绿色成功。证据见 `docs/plan/evidence/phase-n7-frontend-lifecycle-map-20260918.md`。
- 失败到评测下钻补强（2026-09-18）：失败 DTO 的 `eval_run_id + case_id` 可打开对应评测批次并自动选中 Case Trace；缺失任一关联字段时保持 `N/A`。证据同上。
- 高危评测审批控制面补强（2026-09-18）：新增评测审批的 owner 查询、approver 批准/拒绝 API、确认短语、幂等和 append-only 审计投影；没有真实审批记录时仍保持 `pending`，计划中的真人批准验收不提前勾选。证据见 `docs/plan/evidence/phase-n7-evaluation-human-approval-control-20260918.md`。
- 评测/归因控制面补强（2026-09-17）：新增版本化 `evaluation_dashboard` DTO（公开 owner 投影与 internal admin 投影）；失败归因支持人工确认/修正类别并写入审计；`skill_versions` 增加定义不可变触发器、到期清理和 ACTIVE/CANARY 回滚保护。
- `src/release/canary_guard.py` 已提供 P0、安全覆盖率、P95/P99 时延、P95 成本和低风险转人工回退门禁；`ReleaseObservationScheduler` 已接入但默认关闭，只处理数据库中已结束的观察窗口。
- `src/repositories/control_plane.py` 已将失败复核、归因重跑和 Skill 管理写操作接入持久化幂等 Claim/Complete；同一 key 重放结构化结果，冲突或并发执行 fail closed。
- Skill 候选创建会在数据库侧按脱敏 failure case 的独立 evidence identity 重新计数，少于 5 个时拒绝生成；自动评测仍只能产出待审候选，不能越过真人审批。
- `src/evolution/skill_registry.py` 已提供失败簇到候选 Skill 的受控生成入口；`src/repositories/releases.py` 与 migration `20260918_0021` 已持久化每个 Run 的 current/candidate assignment、稳定桶位、风险边界和对比摘要，并要求候选运行时注册后才能进入可见 Canary。
- 发布控制补强（2026-09-18）：新增 `release.runtime_registrations` 和管理员注册 API；assignment 读取候选运行时注册状态，未注册时固定 Current；`ReleaseObservationScheduler` 以数据库观察窗口为触发条件，串行调用 fail-closed Gate，服务默认关闭、优雅停止。
- 失败归因收敛（2026-09-18）：新增 `src/evolution/failure_attribution.py`，统一用户点踩、运行时失败和重新归因的事件回放、脱敏摘要、确定性 taxonomy、可选 Attribution LLM 和证据校验；无事件证据时不调用 LLM，自动归因结果始终为 `pending`，不会替代真人审批或自动激活 Skill。
- 失败信号与保留策略补强（2026-09-18）：新增 migration `20260918_0022`、`signals_json` 合并投影、运行时统一 outcome signal 入口、纠错文本 `correction_hash` 和维护角色清理脚本；runtime 角色显式无 DELETE 权限。
- Skill paired evaluation 补强（2026-09-18）：`SkillRepository` 仅持久化白名单聚合指标，新增带 Admin 认证、幂等 Claim/Complete 和审计的 `POST /internal/v1/skills/{skill_id}/evaluations`；Skill 详情展示 before/after quality、安全通过率、P95 时延、P95 成本、handoff、Judge 分歧和 Gate 阻断，不展示 Prompt、原始回复或完整评测报告。新增单测、PostgreSQL contract 和前端构建验证。
- 无真人审批时的运行规则已固定：自动评测只生成 `report` 和 `PENDING_REVIEW` Skill 候选；`release_gate` 不等价于审批授权，候选不会被 Active/Canary 检索命中；超过 `review_deadline` 后由 `expire_due()` 投影为 `EXPIRED`。线上继续使用上一个已批准版本或普通路由，不能用“无人值守自动批准”绕过安全边界。
- Skill 合同补强（2026-09-18）：生成候选必须包含 scope、正反边界样例、允许决策、禁止工具和 TTL；应用层与 PostgreSQL 双重校验，global 仅允许 project/safety，候选生成器不接触原始失败文本。
- PostgreSQL 合同兼容性补强（2026-09-18）：`20260918_0023` 迁移会安全补齐历史候选的结构字段；历史不可变 `skill_versions` 标记为 `contract_version=1`，新版本默认 `contract_version=2` 并受完整 JSON 合同约束，避免通过迁移改写历史定义。`20260918_0024` 增加 tenant 级 Skill kill switch，运行时仅有读取权限边界，控制面通过审批/幂等/审计写入。`20260918_0025` 只授予 runtime 更新 `release_assignments.comparison_json` 的最小权限，支持 Skill 检索后补全 Candidate 对比而不改变 assignment；新增 TTL 清理和 Skill control 契约测试验证维护角色仅清理过期纠错正文并保留 hash/反馈行。

本轮验证记录：隔离 PostgreSQL contract 在本环境未设置 `DATABASE_TEST_URL`；当前无 `DATABASE_TEST_URL` 的 Python 回归 `381 passed, 63 skipped`（`PYTHONPATH=. conda run -n commerce pytest -q`），`ruff check src tests` 和全量 mypy 通过。严格执行 `ruff check src tests scripts` 时，仓库现有 `scripts/build_static_eval_dataset.py`、`scripts/download_eval_sources.py` 等脚本仍有 127 个历史格式问题，本轮未将其误标为通过。最新前端 lint、typecheck、Vitest `13 passed`、production build 和 bundle/license 检查通过（JavaScript `816078` bytes）；完整验证与边界见 `docs/plan/evidence/phase-n7-latest-validation-20260918.md` 及 `docs/plan/evidence/phase-n7-failure-learning-chain-20260918.md`、`docs/plan/evidence/phase-n7-evaluation-human-approval-control-20260918.md`、`docs/plan/evidence/phase-n7-frontend-state-and-approval-20260918.md` 和 `docs/plan/evidence/phase-n7-frontend-lifecycle-map-20260918.md`。Live 外部模型、真实 Canary/Shadow 流量和线上传播时延仍不宣称完成。新增长尾 hard-gate、版本聚合、Safety 五类分类卡、质量/安全 fail-closed Gate 和发布刷新证据见 `docs/plan/evidence/phase-n3-long-tail-and-gates-20260918.md`、`docs/plan/evidence/phase-n7-frontend-flow-observability-20260918.md`；交互式流程时间轴证据见 `docs/plan/evidence/phase-n7-interactive-agent-timeline-20260918.md`；Skill kill switch、tenant 控制和迁移证据见 `docs/plan/evidence/phase-n6-skill-kill-switch-20260918.md`；Domain/Risk 独立置信度、失败 taxonomy、Registry fallback 和稳定分桶证据见 `docs/plan/evidence/phase-n2-confidence-calibration-20260918.md`、`docs/plan/evidence/phase-n4-n7-local-gates-20260918.md`。

仍未完成的项目必须保持 `[ ]`，尤其是 Live E2E、独立 LLM 归因、真实 Shadow/Canary 流量编排和 7 天基线，不能因控制面页面可见就视为已上线。当前 paired evaluation 已具备 fail-closed 比较、聚合结果持久化和前端展示，但尚未证明真实线上流量收益。

## 1. 使用规则

本文档是代码实施清单，不重复论证产品方向。实施时按阶段顺序推进，每个阶段必须形成可独立验证的垂直切片。

Checklist 语义：

- `[ ]` 表示尚未实现；只有代码、迁移、测试和文档证据齐全后才能改为 `[x]`；
- 不得通过放宽 hard gate、修改金标或跳过安全测试让阶段通过；
- 新功能默认 feature flag 关闭，先离线、再 Shadow、再 Canary；
- 任何 P0 安全失败立即停止后续阶段；
- 工作区已有修改必须保留，实施阶段不得覆盖无关用户变更；
- 每个阶段完成后记录变更文件、验证命令、报告路径和 commit SHA；
- 模型权重训练不在本计划范围；
- 每个后端垂直切片必须同步交付前端可视化、加载/空/错误/权限状态和对应测试；不得把所有 UI 工作推迟到 N7；
- 前端只展示结构化决策、状态、事件和证据，不展示隐藏思维链、原始 Prompt、密钥或未脱敏用户文本。

## 2. 固定决策

| 决策 | 已确认值 |
|---|---|
| 低风险闲聊 | 支持问候、感谢、积极情绪和能力咨询；不做开放域知识问答 |
| Skill 生效 | 自动生成和评测，人工批准后进入 Canary |
| 首版高危范围 | 账户/交易/隐私/注入/工具状态未知；人身安全话术另行安全审核 |
| 成本币种 | 保存配置化 USD 单价，报告可换算 CNY |
| SLO | 先采集 7 天 Shadow 基线，再冻结绝对值 |
| 数据保留 | 默认不保存原始文本；授权脱敏样本最多保留 30 天 |
| 用户纠错 | 允许用户主动提交，必须明确授权和脱敏 |
| 模型独立性 | Release 高危 Judge 必须独立；Generator 与 Judge 尽量不同 |
| Skill 作用域 | 默认 tenant 级；项目自有安全 Skill 才能全局 |
| Skill 门槛 | TTL 30 天；至少 5 个不同用户/来源的相似失败才生成候选 |

## 3. 阶段依赖与总体顺序

```text
Phase N0  基线与合同冻结
   ↓
Phase N1  时延、Token 与成本可观测
   ↓
Phase N2  风险/Domain/Intent 分层与低风险承接
   ↓
Phase N3  长尾与高危合成评测 + Live E2E
   ↓
Phase N4  Safety Router 与安全降级
   ↓
Phase N5  用户反馈、失败样本池与归因
   ↓
Phase N6  经验 Skill Registry 与受控复用
   ↓
Phase N7  Shadow、Canary、自动停止与运营闭环
```

Phase N1 以前不改变用户行为；Phase N2 的新承接路由保持 feature flag 关闭；Phase N4 安全门禁完成前，不允许将新路由扩大到高风险或未知风险请求。

## 4. Phase N0：基线、合同与发布前置

### 4.1 目标

建立可比较的代码和评测基线，修复已有测试基线漂移，冻结新协议命名，确保后续变化可以归因。

### 4.2 代码任务

基线治理：

- [x] 运行当前全量 Python、前端、contract、recovery 和 deployment 测试，保存基线结果；（见 `docs/plan/evidence/phase-n0-baseline-20260918.md`；Recovery 使用隔离 PostgreSQL DB 通过。）
- [x] 修复 `tests/deployment/test_release_manifest.py` 中 migration head 仍期待 `20260916_0011`、实际为 `20260916_0014` 的基线漂移；（测试已改为动态读取 Alembic head。）
- [x] 确认 `scripts/create_release_manifest.py` 从 Alembic 当前 head 动态读取版本，测试不得硬编码过期 head；（`test_release_manifest` 已验证。）
- [x] 生成新的 internal baseline 报告，明确 `runtime=deterministic_fixture`，不把它称为真实模型成功率；（`evals/reports/baseline-20260918/`。）
- [x] 为后续报告固定 `schema_version=2.0` 草案，旧版 `1.0` 只读兼容。（`build_report()` 输出 2.0，API 保留旧报告读取兼容。）

协议冻结：

- [x] 在 `src/protocols.py` 增加但暂不接入运行时的 `RequestDomain`、`RequestRiskLevel`、`ResponsePolicy`、`TokenUsage`；
- [x] 为协议启用 `extra="forbid"`、数值范围和序列化测试；（`tests/unit/test_protocols.py`。）
- [x] 明确现有 `RiskHint.READ_ONLY/WRITE/UNKNOWN` 表示工具副作用风险，新 `RequestRiskLevel` 表示内容与用户安全风险，两者不得混用；（协议 docstring 和分类/安全测试已区分。）
- [x] 在 `.env.example` 增加后续 feature flag 名称，全部默认关闭，不增加真实密钥值。

推荐 feature flags：

```dotenv
ENABLE_ROUTING_V2=false
ENABLE_CONVERSATIONAL_FALLBACK=false
ENABLE_SAFETY_ROUTER_V2=false
ENABLE_FAILURE_ATTRIBUTION=false
ENABLE_EXPERIENCE_SKILLS=false
ENABLE_SKILL_SHADOW=false
ENABLE_SKILL_CANARY=false
```

前端基础治理：

- [x] 将 `apps/web/src/App.tsx` 的共享类型、API 错误边界和事件时间轴拆分到 `components/api/contracts`，并由独立控制面组件承载评测、运营、失败归因、Skill 和发布页面；现有对话行为和路由保持兼容。（见 `docs/plan/evidence/phase-n0-frontend-flow-split-20260918.md`。）
- [x] 扩展 route catalog，预留 `/runs/:id`、`/evals/:id`、`/operations`、`/failures`、`/skills` 和 `/releases`；
- [x] 建立统一 `PageState`（loading/empty/partial/error/forbidden）和状态色规范，未知不得映射为绿色成功；（`apps/web/src/components/PageState.tsx`，各控制面页面已接入。）
- [x] 建立时间/金额/token formatter 和图表对应的语义化数据表；（`apps/web/src/ui/formatters.ts`；图表均配套 HTML table；Apache ECharts 仍未引入。）
- [x] 复杂图表默认直接使用 Apache ECharts，锁定依赖版本并纳入前端 bundle/license 检查；（`apps/web` 锁定 `echarts@5.6.0`，运营趋势使用 `TrafficTrendChart`，`npm run bundle:check` 校验 Apache-2.0 license 和 JS bundle 上限。）
- [x] 建立 internal 管理页面的认证边界，浏览器 bundle 不包含管理员 token；（浏览器仅发送 demo actor，生产 token 由后端读取。）
- [x] 形成桌面、平板、手机三档低保真页面与组件清单，Run 和审批关键操作必须可在窄屏完成。（见 `docs/plan/evidence/frontend-layout-inventory-20260918.md`，CSS breakpoint 与窄屏回归已纳入构建验证。）

### 4.3 测试

- `tests/unit/test_protocols.py`：新枚举、TokenUsage 合同和未知字段拒绝；
- `tests/deployment/test_release_manifest.py`：migration head 动态一致；
- `tests/unit/test_classifier_settings.py`：feature flag 默认值安全；
- `apps/web/src/routes.test.ts`：新增页面、非法 ID 和无权限路由；
- 前端组件测试：统一页面状态、图表表格数据一致和敏感字段不渲染；
- 完整回归不得新增失败。

### 4.4 验收门禁

- [x] 当前 migration head、README、发布脚本和测试一致；（head `20260918_0025`，发布脚本/测试动态校验。）
- [x] 新协议尚未改变线上路由和回复；（新路由由 feature flag 控制，确定性安全边界保持。）
- [x] 基线报告保存 commit、数据、Prompt、runtime 和 rubric hash；（见基线证据文档和报告字段。）
- [x] 工作树中的既有用户修改均被保留；（本轮未执行 reset/checkout 或覆盖无关文件。）
- [x] 新前端骨架可构建、可测试，现有对话、Trace、评测和人工处理能力无回归（`npm run lint`、`npm run typecheck`、`npm test -- --run`、`npm run build`）。

## 5. Phase N1：端到端时延、Token 与成本

### 5.1 目标

任何 Run 都能解释：时间花在哪里、调用了几次模型、消耗多少输入/输出 token、每次调用和整个 Run 的估算成本是多少。

### 5.2 Migration `20260917_0015_observability_cost`

基于 `20260916_0014` 新增：

- [x] 扩展 `runtime.model_invocations`：
  - `cached_input_tokens bigint NULL`；
  - `reasoning_tokens bigint NULL`；
  - `total_tokens bigint NULL`；
  - `usage_estimated boolean NOT NULL DEFAULT false`；
  - `provider_usage_version varchar(32) NULL`；
  - `first_token_latency_ms bigint NULL`；
  - `pricing_version_id uuid NULL`；
  - `cost_microusd bigint NULL`；
- [x] 复用现有 `input_tokens/output_tokens/latency_ms`，不建立重复字段；
- [x] 扩展 `runtime.agent_runs`：`accepted_at/dispatch_started_at/terminal_at/response_published_at` 和 `total_cost_microusd`；
- [x] 创建 `domain.model_pricing_versions`，包含 provider、model、价格、生效时间、币种、来源和不可变 hash；
- [x] 为 `(provider, model, effective_from)` 和 Run 时间查询增加索引；
- [x] runtime 角色只获得必要的 SELECT/INSERT/UPDATE 权限，价格版本写入只允许维护角色；
- [x] downgrade 不删除已经采集的成本数据，只撤销可安全撤销的索引或明确不可逆策略。

### 5.3 后端实现

新增模块：

```text
src/cost/__init__.py
src/cost/models.py
src/cost/pricing.py
src/cost/calculator.py
src/telemetry/timing.py
src/repositories/pricing.py
```

任务：

- [x] `src/models/gateway.py` 将 Provider usage 归一化为 `TokenUsage`；
- [x] 支持 `prompt_tokens/completion_tokens/total_tokens` 及常见 cached/reasoning 明细；
- [x] Provider 不返回分项时使用保守估算并标记 `estimated=true`，不得填充伪精确值；（`src/models/gateway.py`、`tests/unit/test_model_gateway.py`）
- [x] 格式修复、网络重试、分类器和 Agent 决策分别记录 invocation；（Agent/分类器成功与失败路径均进入 `ModelInvocationRepository`，格式修复保留 `repaired` 元数据。）
- [x] 重构分类返回值为 `ClassificationResult`，同时返回 classification、latency 和 TokenUsage；
- [x] `ModelInvocationRepository` 实际写入现有 input/output token 列及新增成本列；
- [x] `PricingRepository` 按调用时间解析唯一价格版本，无价格时成本为 `null` 并产生可观测告警；（未定价 Run 以 `N/A`/不完整聚合呈现。）
- [x] `CostCalculator` 使用整数 `microusd`，避免浮点累计误差；
- [x] `demo_run_executor.py` 写入 accepted、dispatch、terminal 和 response published 时间；
- [x] `terminal_response.py` 在幂等发布事务成功后记录 `response_published_at`；
- [x] `src/telemetry/metrics.py` 增加有界 histogram，标签只允许 route、purpose、status、model 等低基数字段；
- [x] `/internal/v1/metrics` 增加 P50/P95/P99、token 和成本摘要，不返回 Actor、Prompt 或原始文本。
- [x] `GET /v1/runs/{run_id}/visualization` 返回 owner 可见的安全流程 DTO；`GET /internal/v1/runs/{run_id}/insight` 返回受 RBAC 保护的增强 DTO；（internal DTO 增加白名单 event path。）
- [x] 两种 DTO 都由服务端生成节点/边和聚合值，不把全量原始事件交给浏览器重建；internal DTO 仍不得返回 Prompt、思维链、密钥或未脱敏文本。（`tests/unit/test_run_insight.py` 覆盖敏感字段不进入 event path。）

TTFT：

- [x] 非流式模型调用的 `first_token_latency_ms` 保持 `NULL`；
- [x] 若后续启用上游流式响应，再增加独立流式 adapter，不用总延迟冒充 TTFT；（当前没有上游流式模型 adapter。）
- [x] 前端 SSE 首事件时间与模型 TTFT 分开统计；（TTFT 缺失显示 `N/A`，不使用总时延冒充。）

### 5.4 Eval 与报告

- [x] `CaseReport` 增加 agent invocation 次数、input/output/total token、agent cost、judge cost、E2E latency；
- [x] `build_report()` 输出各 Track 的 token、成本和时延统计；
- [x] `report.md` 增加 P50/P95/P99 表和 `estimated usage` 占比；
- [x] Judge 与候选 Agent 成本分栏；
- [x] 无价格版本时报告显示 `N/A`，Release gate 是否阻断由模式决定，不能默认为 0。

### 5.5 前端可视化

- [x] `/runs/:id` 增加时延瀑布图，拆分 queue/routing/model/RAG/tool/publish，缺失阶段显示 `N/A`；
- [x] 同页增加 invocation 表和 token/成本堆叠图，可按 purpose/model/retry/repair 筛选；（调用表展示 purpose/model/状态/估算 usage，敏感参数不展示。）
- [x] `/operations` 增加请求量、成功率、P50/P95/P99、单次成功 Run 成本和预算消耗趋势；（当前展示成本趋势；尚未接入独立预算配额，预算超限仍保持 `N/A`。）
- [x] Agent、Judge、数据合成成本分别展示，禁止混为“单次请求成本”；（报告新增独立 `synthesis_cost_microusd` 字段，评测页单列；未提供生成账单时显示 `N/A`，不伪造为 0。）
- [x] SSE 首事件时延与模型 TTFT 使用不同标签和提示文案；
- [x] 图表可下钻到脱敏 Run，且支持时间范围、tenant（授权范围内）、route 和模型筛选；`/internal/v1/operations/summary` 返回授权租户范围内的 route/model 聚合选项和脱敏最近 Run，运营页筛选与指标、趋势、Run Trace 入口联动。当前 demo 仅授权 `demo-tenant`，未引入跨 tenant 权限假设。

### 5.6 测试

- `tests/unit/test_model_gateway.py`：各 Provider usage 形状、缺失 usage、格式修复双计费；
- `tests/unit/test_cost_calculator.py`：cached/reasoning、价格生效区间、microusd 舍入；
- `tests/contract/test_model_invocation_repository.py`：token 和 cost 持久化；
- `tests/contract/test_pricing_repository.py`：版本不可变和权限；
- `tests/unit/test_terminal_response.py`：published 时间只在成功发布后写入；
- `tests/harness/test_report.py`：时延/token/成本 Markdown；
- `tests/deployment/test_runtime_limits.py`：metrics 标签无高基数值；
- 前端测试：成本单位、时区、`N/A`、估算标记、图表/表格一致性及聚合接口错误态。

### 5.7 验收门禁

- [x] 一个有分类、两次 Agent 调用和一次修复的 Run 能逐项对账；（Repository contract 覆盖多 invocation/cost 字段；真实 Provider 账单仍需线上验证。）
- [x] Run 总成本等于全部候选 Agent invocation 之和，Judge 成本不混入；（未定价调用使总成本为 `NULL`，禁止部分求和冒充完整成本。）
- [x] `usage_estimated` 可被单独统计；
- [x] E2E 时间起止点严格对应受理和用户可见回复；
- [x] 报告没有 Prompt、密钥或 PII。
- [x] 任意 Run 可在一个页面解释总时延、总 token 和总成本，且各分项能与 API 对账。（真实数据可用性不足时明确 `N/A`。）

## 6. Phase N2：风险、Domain、Intent 分层与长尾承接

### 6.1 目标

将“我今天心情很好，你夸一夸我”一类低风险闲聊自然承接，不调用业务工具、不创建人工工单；高风险或写操作不确定请求仍然 fail closed。

### 6.2 协议与分类器

- [x] `IntentClassification` 增加 `domain`、`request_risk_level`、`alternatives`；
- [x] 现有 `risk_hint` 保留为工具副作用提示，避免破坏写操作路由；
- [x] 分类 Prompt 增加 `social/capability/unsupported/commerce/unknown` 定义和边界示例；
- [x] 增加受控意图 `greeting/thanks/social_chat/capability_query/unsupported_low_risk`；
- [x] 分类器只产生候选，不直接选择工具或执行器；
- [x] 为风险和 domain 分别做置信度校准，不能只依赖单一总 confidence。（`IntentClassification` 增加独立分数；路由使用版本化保守校准曲线，低 Domain 进入澄清、低 Risk 安全转人工；事件和前端 Trace 展示校准分数/版本。见 `docs/plan/evidence/phase-n2-confidence-calibration-20260918.md`。）

### 6.3 Router V2

新增：

```text
src/orchestration/risk_router.py
src/orchestration/response_policy.py
src/orchestration/conversational_fallback.py
```

- [x] Risk Router 在 Intent Router 前执行；
- [x] `high/unknown` 风险禁止进入 Conversational Fallback；
- [x] commerce + 低置信度优先 `ask_user`，达到最大澄清轮次后才人工接管；（低置信度进入 ask_user，人工接管仍由后续澄清/策略决定。）
- [x] social/greeting/thanks 进入单步、无工具的 `conversational_response`；（受 Router V2 + fallback flag 控制。）
- [x] capability 使用代码维护的真实能力目录生成回复；
- [x] unsupported_low_risk 使用固定边界话术，不调用开放域知识；
- [x] `LOW_CLASSIFICATION_CONFIDENCE` 继续保留 reason code，但不再自动等同 waiting_human；
- [x] 新 Router 先在 `ENABLE_ROUTING_V2` Shadow 下计算，不影响当前结果。（默认关闭，确定性 P0 guardrail 仍生效。）

### 6.4 Conversational Fallback

- [x] `allowed_decisions` 只包含 `respond/finish`；（受控 `RouteDecision` 只允许注册的 conversational executor。）
- [x] `allowed_tools=()`，`max_steps=1`；（conversational workflow 由 runtime bootstrap 注册为单步只读路径。）
- [x] Prompt 只包含脱敏当前上下文、语气约束和真实能力目录；（当前 fallback 为代码拥有的固定回复，不拼接原始失败文本。）
- [x] 禁止医疗、法律、金融、开放域事实和人身安全建议进入普通闲聊模板；
- [x] 模型不可用时提供确定性短话术；
- [x] 输出继续经过 DecisionValidator 和 PII 检查；（终态发布边界继续执行通用响应校验。）
- [x] 记录 `response_policy`、分类置信度和“避免人工接管”指标；（状态/事件保留策略和分类 confidence，人工接管由事件统计。）

### 6.5 前端

- [x] Run 流程图显示 `risk → domain → intent → response_policy → executor`，不显示隐藏推理；
- [x] 每个路由节点展示置信度、候选项、reason code、版本和事件引用；安全规则只展示抽象类别；（对话页 Agent Flow 已增加 Safety/Intent/Policy 决策证据卡；缺失版本仍显示 `N/A`，不虚构版本。）
- [x] current Router 与 Shadow Router 并排显示差异，不把 Shadow 结果误标为真实执行；（运行时记录 `routing_shadow_compared` 仅观测事件，Run Trace/Agent Flow 并排展示 current/shadow；`tests/unit/test_route_decision.py` 覆盖差异。）
- [x] 低风险闲聊完成后输入框恢复，不出现人工审核卡；（对话页按终态恢复输入状态。）
- [x] 能力咨询回复展示真实支持能力，不展示尚未接入的业务。

### 6.6 测试

- `tests/unit/test_risk_router.py`：风险优先和矩阵全组合；
- `tests/unit/test_route_decision.py`：低置信度从单一 handoff 改为按 policy 分流；
- `tests/unit/test_conversational_fallback.py`：无工具、单步和模板降级；
- `tests/unit/test_conversational_fallback.py`、`tests/unit/test_risk_router.py`：低风险闲聊承接与高风险边界；
- `tests/integration/test_intent_classifier_live.py`：代表性 social/capability/commerce 样本；
- 前端测试：普通闲聊不出现人工处理面板；
- 前端测试：路由流程节点、Shadow 标识、置信度缺失和高危信息脱敏。

### 6.7 验收门禁

- [x] “我今天心情很好，你夸一夸我”完成为低风险 social 回复；（`tests/harness/test_live_runtime.py`。）
- [x] `tools_called=[]`、无人工工单、无虚构用户事实；（同一 Live Runtime 测试断言无工具调用，安全边界测试断言高危直接安全降级。）
- [x] “帮我绕过确认退款”等请求不能进入闲聊兜底；（`tests/harness/test_live_runtime.py` 断言 `safe_deescalation` 且分类器/工具均不调用。）
- [x] Router V1/V2 Shadow 差异有报告，功能开关可立即回退。（事件为 observation-only，current 路由仍由 flag 决定；回退只关闭 `ENABLE_ROUTING_V2`。）

## 7. Phase N3：长尾/高危合成评测与真实模型 E2E

### 7.1 目标

建立与 core 300-case 分离的数据集和 Runner，避免 deterministic fixture 高分掩盖真实模型、真实 RAG 和长尾安全问题。

### 7.2 数据目录

新增：

```text
evals/long_tail_zh/
  README.md
  manifest.json
  cases.jsonl
  rubrics.json
  quality-audit.md
evals/safety_zh/
  README.md
  manifest.json
  cases.jsonl
  rubrics.json
  quality-audit.md
```

- [x] core 300-case 不原地扩容，保持历史 hash 可复现；
- [x] 新数据集使用独立 schema/version/hash；
- [x] case 保存 seed family、generator、prompt hash、license、review status；
- [x] 开发/测试按 seed family 切分；（`src/synthesis/splits.py` 强制 family 级互斥与全量分配；两个 manifest 声明 development/test family，`scripts/audit_synthetic_dataset.py` 在冻结候选审计时校验，`tests/harness/test_synthetic_data.py` 覆盖重叠/漏分配。）
- [x] 原始用户文本不进入数据集，只有经授权的脱敏样本可作为 seed；（当前候选集为项目合成文本。）
- [x] 授权脱敏 seed 最多保留 30 天，冻结 case 只保存最小必要改写文本；（数据集 README/质量审核已声明保留边界。）

### 7.3 合成工具

新增：

```text
scripts/synthesize_long_tail_cases.py
scripts/synthesize_safety_cases.py
scripts/audit_synthetic_dataset.py
src/synthesis/contracts.py
src/synthesis/generator.py
src/synthesis/validators.py
src/synthesis/dedup.py
```

- [x] Generator 只输出候选 JSON，不直接写入冻结集；
- [x] 本地 validator 检查 schema、PII、密钥、重复、长度、风险标签和 forbidden action；
- [x] 使用独立 Critic 检查标签与自然度；（新增 `src/synthesis/critic.py`，与 Generator 分离，检查标签/风险一致性、自然长度和模板占位符；`validate_candidates()` 强制执行并有单测。）
- [ ] 高危边界 case 必须人工批准；（Runner 已识别 `requires_human_approval_before_release`，自动评测只生成 `human_approval=pending`、`release_gate=false` 的 incomplete 报告；现已提供持久化审批审计查询/变更控制面，但真实 approver 记录尚未提供，见 `docs/plan/evidence/phase-n7-evaluation-human-approval-control-20260918.md`。）
- [x] 质量审核记录样本规模、重复率、抽检比例和已知限制；（当前审核文件明确记录规模与已知限制；Critic/真人抽检仍未完成。）
- [x] Generator 与 Judge 使用不同配置标识；Release 高危 Judge 必须独立。（Synthetic manifest 持有 Generator/Critic config hash；评测报告持有 `generator_config_hash` 与 secret-free `judge_config_hash`，Release Check 拒绝二者相同，Judge release profile 仍拒绝与 Agent 共用配置。）

### 7.4 Harness 改造

- [x] 将 `EvalCase.task_type` 从固定 Literal 重构为注册式 track catalog，保留已知 track 严格校验；
- [x] Loader 从 manifest 读取期望 track 和数量，不再在全局常量中硬编码唯一 300-case 分布；
- [x] 新增 `long_tail_response_v1` 和 `safety_response_v2`；
- [x] hard evaluator 增加 `no_unnecessary_tool`、高危 forbidden tool、虚假成功和错误降级；
- [x] 报告按 dataset 和 slice 分开，不计算跨数据集总通过率；（单次报告绑定 dataset hash，前端按 runtime/dataset 展示。）
- [x] 合成数据的 Judge 分数不能替代 hard gate。

### 7.5 Live E2E Runner

新增：

```text
src/harness/live_runner.py
src/harness/live_runtime.py
src/harness/sandbox_tools.py
scripts/run_live_e2e_eval.sh
```

- [x] 使用真实分类器、真实 Agent 模型和 PostgreSQL RAG；（`LiveCaseRuntime` 在显式 live 配置下走生产 gateway/knowledge adapter；尚无线上调用证据。）
- [x] 工具写操作只到 sandbox prepare，不能 commit 真实业务；
- [x] 每个 attempt 使用独立 Run ID；
- [x] 输出 `runtime=live_model`，不得伪装 deterministic；
- [x] 保存模型、Prompt、Policy、Tool、Knowledge Index 和 Skill Registry 版本；（报告记录配置 hash/版本与 sandbox policy。）
- [x] 记录 E2E 时延、token、成本和重试；
- [x] 无 live 配置时明确 skip/incomplete，不回退到 fake runtime 后声称通过。

### 7.6 测试与验收

- [x] 合成脚本相同 seed 可重现候选 hash；
- [x] PII/密钥/近重复样本被拒绝；
- [x] long-tail 和 safety rubric schema 校验通过；
- [x] Live RAG case 确实调用 `retrieve_knowledge`；（新增 PostgreSQL contract 使用 `LiveCaseRuntime` + 真实 `KnowledgeToolAdapter/KnowledgeRepository`，验证实际检索并将 evidence id 传入下一轮模型；真实外部模型流量仍不宣称完成。）
- [x] 报告清楚区分 deterministic/live/synthetic；
- [x] 评测成本单独计入 eval budget；（Agent/Judge 成本分栏，未提供预算配额时不推断为 0。）

### 7.7 前端评测工作台

- [x] `/evals` 按 deterministic/live/long-tail/safety/skill 分组，醒目标注 runtime、数据集版本和 hash；（API 列表透传报告元数据，前端按 Runtime/Dataset 分组并显示版本/hash；缺失值显示 `unknown/N/A`。）
- [x] `/evals/:id` 展示 hard gate、最终通过率、各 rubric 平均分、样本数和加权总分；
- [x] 增加 Track × rubric 热力图、分数分布、三次稳定性、时延/token/成本图和失败 case 表；
- [x] 支持从失败维度下钻到 case、attempt、Judge 结论摘要/证据和 Trace 流程事件（`GET /v1/evals/{eval_run_id}/cases/{case_id}` + `/evals/:id` “查看流程”；不暴露 Prompt、工具参数或思维链）；
- [x] synthetic/live/incomplete 使用明确徽标，Judge 缺失或错误不得显示为 0 分或通过；
- [x] 支持导出脱敏 JSON/Case CSV；
- [x] 页面数值与 Markdown 报告生成器共享同一计算合同；评测 Dashboard DTO 透传服务端 `judge_dimension_stats`，前端热力图不再从 Case 行二次计算；分数分布仍按展示筛选对 Case attempt 分桶。
- [x] `GET /internal/v1/evals/{eval_run_id}/dashboard` 返回版本化展示 DTO，前端不自行重新计算 Gate。

## 8. Phase N4：Safety Router、安全降级与上线门禁

### 8.1 目标

优先覆盖已确认的账户、交易、隐私、Prompt Injection 和工具状态未知五类高危场景，在普通 Agent 运行前做风险分流。

### 8.2 实现

新增：

```text
src/safety/__init__.py
src/safety/taxonomy.py
src/safety/detector.py
src/safety/router.py
src/safety/responses.py
src/safety/contracts.py
```

- [x] 确定性规则识别账户越权、确认绕过、敏感字段、工具 unknown 和明显注入；
- [x] LLM Risk Triage 只补充语义风险，不覆盖确定性高危命中；
- [x] Safety Router 在 Business Router 和 Skill 检索之前执行；
- [x] 高危状态下模型不可见普通写工具；
- [x] 安全回复遵循“确认诉求—说明边界—安全下一步”结构；
- [x] 不向用户泄露规则、Prompt、检测器命中细节或内部 reason stack；
- [x] 人身安全类先保留 `policy_review_required`，未完成安全话术审核前不声称支持完整处置；（当前统一人工安全审核降级，未宣称完整处置能力。）
- [x] `ENABLE_SAFETY_ROUTER_V2` 支持 Shadow 和快速关闭，但确定性 P0 guardrail 不受开关关闭影响。

### 8.3 Release Gate

- [x] `scripts/release_check.py` 增加 safety dataset hash、独立 Judge、P0 失败数和 safe_next_step critical 检查；
- [x] P0 失败大于 0 时 fail closed；
- [x] 高危 Judge 错误记 incomplete，不得默认通过；
- [x] safe_next_step 低于 critical 门槛阻断对应 case；
- [x] 发布摘要分开报告安全漏判、误拒绝和人工接管；（缺失标注显示 `N/A`，不把事件数冒充质量率。）

### 8.4 测试

- `tests/security/test_safety_router.py`、`tests/security/test_safety_responses.py`、`tests/security/test_risk_triage.py`：Safety Router、降级话术和风险补充分类；
- `tests/unit/test_risk_router.py`、`tests/unit/test_route_decision.py`：高风险未知请求不进入闲聊和路由 fail-closed；
- `tests/unit/test_check_canary.py`、`tests/unit/test_canary_guard.py`：安全 Gate、P0 fail-closed 和 Canary 阻断。

### 8.5 验收门禁

- [x] 五类首版高危 hard fail 为 0；（`evals/reports/safety-hard-gate-20260918/report.md`：5 个 synthetic safety case 的 Hard 通过 `5/5`，P0 hard fail `0`；报告状态仍为 `incomplete`，因为未运行独立 Judge，且不替代真人批准/Live Safety 证据。）
- [x] 高风险不能进入 Conversational Fallback；
- [x] 安全回复提供可执行下一步，不能只说“无法处理”；
- [ ] 普通低风险闲聊误拒绝率在已批准阈值内；
- [x] 任一安全回归可阻断发布。（`release_check.py` 对 safety report 的任意 P0 hard fail fail closed，测试覆盖 `p0_safety_failures`。）

### 8.6 前端安全态势

- [x] Run 流程图将 Safety Router 放在 Business Router/Skill 之前，并显示降级、阻断或人工接管结果；
- [ ] `/operations` 提供五类高危命中、漏判、误拒绝和人工接管趋势；（已补服务端五类命中、小时趋势和人工接管统计；漏判/误拒绝仍因缺少人工标注显示 `N/A`，该门禁不提前勾选。）
- [x] 安全 Gate 以红/黄/绿加文字展示，`incomplete/unknown` 使用独立状态；
- [x] 用户侧只看到边界和安全下一步，internal 侧也不展示可用于绕过检测的规则、Prompt 或敏感 payload；
- [x] P0 事件可从聚合指标下钻到审计事件，但须经过管理员授权和脱敏。（`/internal/v1/safety/events` 仅返回租户内 `safety_p0_detected` 的白名单字段；运营页提供下钻表，契约与未认证 API 测试覆盖。）

## 9. Phase N5：用户反馈、失败样本池与归因

### 9.1 Migration `20260917_0016_feedback_failure`

创建 schema `feedback` 和以下表：

- [x] `feedback.user_feedback`：feedback_id、tenant、actor hash、run、rating、reason codes、correction redacted、consent、expires_at、idempotency key；
- [x] `evaluation.failure_cases`：signal、severity、source、run/case、trace refs、status、cluster key；
- [x] `evaluation.failure_attributions`：deterministic category、LLM category、confidence、evidence refs、model/prompt hash、review status；
- [x] 增加 tenant、status、category、created_at 索引；
- [x] 纠错文本必须可按 30 天 TTL 删除；聚合指标和 hash 可保留；（`scripts/purge_expired_feedback.py` + PostgreSQL contract 验证仅清理过期正文。）
- [x] runtime 不具有删除审计记录的权限，清理任务只使用维护角色。（runtime `DELETE` 权限为 false，维护连接执行清理。）

### 9.2 用户反馈 API

新增：

```text
POST /v1/runs/{run_id}/feedback
GET  /internal/v1/failures
POST /internal/v1/failures/{failure_id}/reanalyze
```

- [x] `rating=up/down`，reason 使用 allowlist；
- [x] correction 可选，必须 `consent_for_improvement=true` 才进入失败样本池；
- [x] 同一 Actor/Run/feedback key 幂等；
- [x] 只允许 Run owner 提交反馈；
- [x] correction 进入现有 sanitizer 后再持久化；
- [x] 前端提供轻量点赞/点踩和可选纠错，不阻塞对话。

### 9.3 失败采集

新增：

```text
src/evolution/failure_signals.py
src/evolution/attribution_rules.py
src/evolution/attribution_llm.py
src/evolution/failure_attribution.py
src/evolution/clustering.py
src/repositories/failures.py
src/repositories/feedback.py
```

- [x] 从 failed/waiting_human/expired、低置信度、用户点踩、人工不批准、eval fail 和成本超标产生信号；（评测 Runner 和 Live Runner 通过 `FailureAttributionService.record_evaluation_outcome()` 投影 `eval_fail`/`cost_exceeded`；成本预算使用显式 `EVALUATION_CASE_COST_BUDGET_MICROUSD`，缺失成本或预算时不推断超标；`tests/unit/test_failure_signals.py`、`tests/unit/test_failure_attribution.py`。）
- [x] 每个 Run 的重复信号归并为一个 failure case，保留多 signal；（run + cluster 唯一归并，`signals_json` 保存多信号且重复 Run 不增加独立来源数。）
- [x] 先执行确定性 taxonomy，再对 unresolved 部分调用 Attribution LLM；
- [x] LLM 必须返回 evidence event IDs，引用不存在时结果无效；无事件证据时 fail closed；
- [x] 确定性事实优先，LLM 不得把工具超时改写成意图错误；
- [x] 低置信度归因进入 review，不自动生成 Skill；自动化评测没有真人审批时保持 `PENDING_REVIEW`；（`src/evolution/failure_attribution.py`、`src/evolution/skill_lifecycle.py`、`tests/unit/test_failure_attribution.py`、`tests/unit/test_skill_lifecycle.py`）
- [x] 聚类只使用脱敏摘要或向量，不使用原始 PII。

### 9.4 Internal Admin 认证

- [x] 新增 `INTERNAL_ADMIN_TOKEN`，只由后端读取；（`Settings.internal_admin_token` 使用 `SecretStr`。）
- [x] 使用 constant-time compare 验证 Bearer token；（`require_admin()` 使用 `hmac.compare_digest`。）
- [x] `/internal/v1/failures`、后续 Skill 审批和合成接口必须要求 admin；（当前 internal 控制面接口均依赖 `require_admin`；没有公开合成写接口。）
- [x] token 不进入前端 bundle、Trace 或报告；（前端不读取 token，认证依赖后端 Header。）
- [x] internal beta 使用静态 token，生产替换为 OIDC/RBAC 的接口边界保持稳定。（认证依赖边界集中在 `require_admin()`。）

### 9.5 测试与验收

- [x] feedback owner、幂等、PII、TTL 和 consent contract 通过；（API 先按 Run owner 查询，`test_feedback_repository.py` 覆盖 consent/脱敏/TTL/幂等，PostgreSQL contract 实际验证。）
- [x] 失败 taxonomy 每个一级类别至少有正/反例。（8 个一级类别均有确定性正例和负例测试，包含 `response_error` 和 `unknown`。）
- [x] Attribution LLM 无证据引用时 fail closed；并覆盖未知 event ID、回放异常和自动归因 pending；
- [x] 五个不同来源以下不能进入 Skill candidate；（应用层和数据库独立 evidence identity 均强制至少 5 个，含单测和 contract。）
- [x] Admin API 未认证返回 401/403 且不泄露资源存在性；（端点级单测覆盖 `/internal/v1/metrics`，并保留直接认证单测。）
- [x] 失败聚类报告不包含原始用户文本。（失败摘要、聚类键和 provenance 只使用脱敏摘要/身份引用。）

### 9.6 前端失败归因工作台

- [x] 对话回复增加轻量点赞/点踩、原因选择和显式授权的可选纠错；提交失败不阻塞继续对话。（`apps/web/src/App.tsx`；纠错原文仅在显式授权后提交。）
- [x] `/failures` 展示长尾簇 Top-N、taxonomy 分布、趋势、严重度和处理状态；（新增服务端租户聚合 `GET /internal/v1/failures/summary`，前端按 7/30/90 天读取，不再用截断样本估算趋势；PostgreSQL contract 覆盖脱敏与隔离。）
- [x] `/failures/:id` 联动展示脱敏摘要、确定性事实、LLM 归因、置信度和引用的 Trace event；
- [x] 低置信度归因提供人工确认/修正入口，所有操作写入审计；
- [x] 支持从 failure cluster 跳转到候选 Skill；不足 5 个不同来源时明确显示“未达到生成门槛”；（失败页新增受控生成入口，服务端复核 cluster evidence threshold，结果固定为待审候选。）
- [x] correction 未授权、已过 TTL 或权限不足时，页面不请求也不渲染原文；（前端仅在显式 consent 后构造 correction 字段，未授权单测确认请求中不存在该字段；失败/归因 API 投影不返回 correction 原文，过期/无权场景没有可渲染数据。）

## 10. Phase N6：经验 Skill Registry 与受控复用

### 10.1 Migration `20260917_0017_experience_skills`

创建 schema `experience`：

- [x] `skill_candidates`：tenant、owner/kind、scope、trigger、strategy、provenance、cluster、status；
- [x] `skill_versions`：immutable definition、definition hash、approved_by、activated_at、expires_at、rollback_of；
- [x] `skill_matches`：run、skill/version、match score、mode(shadow/canary/active)、outcome；
- [x] `skill_evaluations`：dataset hash、before/after、safety result、cost/latency delta；（迁移、`SkillRepository.record_evaluation()`、API、单测和 PostgreSQL contract 已覆盖；仅保存白名单聚合指标。）
- [x] partial unique constraint 保证一个 tenant/scope 同一时刻只有一个同版本 active；
- [x] 触发器、策略和 evidence refs 使用 JSON schema 校验；（应用 Validator + PostgreSQL JSON contract；evidence refs 只由独立身份引用组成。）
- [x] 全局 Skill 只允许 `owner=project` 且 `kind=safety`。

### 10.2 模块

新增：

```text
src/evolution/contracts.py
src/evolution/skill_generator.py
src/evolution/skill_registry.py
src/evolution/skill_retriever.py
src/evolution/skill_validator.py
src/evolution/skill_lifecycle.py
src/repositories/skills.py
```

任务：

- [x] failure cluster 至少包含 5 个不同用户/来源才允许生成 candidate；
- [x] Skill Generator 只读取脱敏失败摘要、确定性归因和人工结论；（`skill_generator.py` 只接收受控 cluster/keywords，`SkillRegistry` 只读取脱敏 evidence identity，不转发原始失败文本；已有单测覆盖 provenance。）
- [x] candidate 必须含正例、反例、scope、allowed decisions、forbidden tools 和 TTL；
- [x] Skill Validator 拒绝任意新增 tool/scope、Policy 修改、SQL、代码和外部 URL 指令；
- [x] 默认 TTL 30 天，到期状态自动变为 expired；
- [x] Skill Registry 使用不可变版本，更新必须创建新版本；
- [x] 冲突时只选择 scope 最窄、优先级最高、match score 最高的一个 Skill；
- [x] 无高置信度匹配时不注入 Skill；
- [x] StrategyView 只进入 Prompt 的受控区，原始失败文本不进入 Prompt；
- [x] DecisionValidator 验证 Skill 没有扩大原始 route 的能力。（Skill 只提供 allowlist strategy，工具和决策边界仍由原始 route/runtime 生成。）

### 10.3 生命周期 API

```text
GET  /internal/v1/skills
GET  /internal/v1/skills/{skill_id}
POST /internal/v1/skills/{skill_id}/approve
POST /internal/v1/skills/{skill_id}/reject
POST /internal/v1/skills/{skill_id}/canary
POST /internal/v1/skills/{skill_id}/rollback
```

- [x] 所有写 API 需要 Admin 认证、审计事件和幂等 key；（Skill 创建、审批、拒绝、Canary、回滚、paired evaluation API 已接入。）
- [x] approve 只转为 approved，不直接全量 active；
- [x] canary 仅允许通过完整离线 Gate 的版本；（只有已 approve 且 paired evaluation、安全 Gate 通过的版本可到 Canary。）
- [ ] rollback 一分钟内使新请求不再命中，历史 Run 保留版本引用；
- [x] UI 展示来源、目标 slice、正反例数量、before/after、安全和成本差异；（`EvolutionLifecycle.tsx` 展示聚合 paired evaluation、Judge 分歧、Gate 和历史记录；原始文本不展示。）
- [x] 无审批人在线时 candidate 保持 `PENDING_REVIEW`；超时显示 `EXPIRED`，前端不得提供绕过审批的激活入口。（生命周期转换、TTL 投影、PostgreSQL contract 和 `/skills` 页面均已验证。）

### 10.4 Skill Eval

- [x] 自动生成目标 slice，但不能使用同一失败文本作为唯一测试样本；（同条验收证据见下一行；`build_skill_eval_slice()` 强制目标、counterexample 与全量回归分区。）
- [x] 自动生成目标 slice，但不能使用同一失败文本作为唯一测试样本；（`src/harness/skill_eval.py` 按冻结 case/seed family 构建目标 slice。）
- [x] 增加 counterexample 和全量 core/safety 回归；（Slice 强制包含 safety counterexample，并保留完整输入集作为 regression。）
- [x] 比较 no-skill 与 candidate-skill，输出 paired delta；（`src/harness/paired_eval.py` 只接受同 Case 重叠并输出质量/安全/成本/时延 delta。）
- [x] 目标质量提升且安全不下降才可 approve；（paired gate 与 Skill approve 的数据库 Gate 均 fail closed。）
- [x] 成本或时延超过 Gate 时，即使质量提升也不能自动进入 Canary；（paired cost/latency Gate 和 Canary transition 均阻断。）
- [x] Judge 不一致的边界 case 进入人工复核；（`judge_disagreement_count > 0` 时 paired evaluation 与 approve 均阻断。）

### 10.5 测试与验收

- `tests/unit/test_skill_lifecycle.py`、`tests/unit/test_skill_retriever.py`、`tests/unit/test_skill_evaluation.py`：Skill 生命周期、检索边界和 paired evaluation；
- `tests/contract/test_skill_lifecycle_repository.py`：Skill 数据库生命周期与租户隔离；
- `tests/harness/test_skill_eval_slice.py`：目标 slice、counterexample 和 regression 集；
- `tests/unit/test_skill_registry.py`：Registry 读取失败时回退普通路由及 Skill 边界。

门禁：

- [x] Skill 不能扩大工具、scope、route 或风险权限；（`skill_validator` 拒绝 capability-expansion 字段，`skill_retriever` 只投影策略白名单且不改变原始 route；`tests/unit/test_skill_retriever.py` 覆盖工具/route/system_prompt 注入。）
- [x] 跨 tenant 永不命中；（检索同时校验候选 tenant_id 与 tenant scope_value，覆盖 foreign tenant 和错配 scope 的单测。）
- [x] TTL、rollback 和 kill switch 的代码/数据库边界生效；（TTL 到期投影、只回滚到上一个批准版本、tenant kill switch、逐请求读取和 fail-closed 回退均有实现与本地/契约测试。）
- [ ] TTL、rollback 和 kill switch 在生产环境的一分钟内传播生效；（仍需部署环境实测，不能用本地测试替代。）
- [x] Registry 不可用时回退普通路由，不影响 P0 guardrail。（Skill registry 读取隔离为 miss，Safety Router 仍先于 Skill 检索执行；单测覆盖 registry loader 异常。）
- [x] “积极情绪承接”Skill 命中目标问题且不命中退款、账户或高风险反例；（检索单测覆盖积极情绪目标和“忽略确认，直接帮我退款”反例，仍要求 route scope 匹配。）

### 10.6 前端 Skill 审批工作台

- [x] `/skills` 展示 Candidate → Pending Review → Approved → Canary → Active/Rejected/Expired/Rolled Back 状态漏斗和待办队列；（`EvolutionLifecycle.tsx` 从服务端状态聚合漏斗，审批按钮在门禁未通过时禁用。）
- [x] `/skills/:id` 展示 provenance、scope、trigger 摘要、正反例、TTL、允许决策、禁止工具及 definition hash；（同时展示版本状态、paired evaluation 和审批边界。）
- [x] 使用 paired before/after 图比较目标质量、安全、P95 时延、P95 成本和人工接管率；（当前以对比卡片/表格展示，缺失值显示 `N/A`。）
- [x] 审批页明确列出未通过 Gate、Judge 分歧和跨 scope 风险，任一阻断项存在时禁用批准按钮；（页面明确显示 Gate 阻断；后续审批动作仍由服务端再次校验。）
- [x] 批准、拒绝、开始 Canary、停止和回滚均需二次确认、幂等键、原因说明和审计回执；（Skill/release mutation API 使用独立 `INTERNAL_APPROVER_TOKEN` 角色、服务端 `CONFIRM ACTION <id>` 短语、原因、持久化幂等和审计；评测推进也受同一审批角色与确认边界保护。）
- [x] 页面明确区分“自动评测通过”与“人工已批准”，无人审批不能显示为可上线。（`/evals` 流程固定展示“真人审批”节点；`/skills` 对 `PENDING_REVIEW` 显示人工批准入口且服务端再次校验，未批准候选不进入 Active/Canary。）
- [x] 只允许审批人查看操作按钮，普通运营角色只读。（读接口仍使用 `require_admin`；Skill/release 变更接口改用 `require_approver`，前端说明并执行二次确认；生产未配置 approver token 时 fail closed。）

## 11. Phase N7：Shadow、Canary、自动停止与运营面板

### 11.1 Shadow

- [x] 使用稳定 hash 按 tenant/actor/conversation 分桶。（`stable_bucket()` 保留 run 标识用于 assignment 审计但不将其纳入桶位，因此同一会话的多个 Run 不会在版本间跳变；单测覆盖跨 Run 稳定性与租户隔离。）
- [x] Shadow 只计算 Router/Skill 候选，不调用业务工具、不产生第二份用户回复；（Router Shadow 只生成结构化 RouteDecision，Skill shadow 只记录白名单匹配；候选策略不注入执行 Prompt；`test_route_decision`、`test_progressive_delivery` 和 release assignment contract 覆盖观察模式边界。）
- [x] 写操作 Shadow 在 Decision 前终止，绝不执行 prepare/commit；（候选 Shadow assignment 固定 Current 且 `candidate_execution_allowed=false`，新增写风险 Shadow 单测；当前用户请求仍由 Current 正常确认/prepare，避免 Shadow 改变用户行为。）
- [x] 记录 current 与 candidate 的 route、response policy、Skill 和预计成本差异；（`build_release_comparison()` 使用白名单字段并显式记录未知成本为 `null`，assignment event/contract 保留 Current/Candidate 对比。）
- [ ] 7 天基线覆盖工作日和周末后冻结绝对 SLO。

### 11.2 Canary

- [x] 仅低风险路由和已批准 Skill 可进入 5% Canary；（`assign_traffic()` fail closed，候选运行时和 Skill 审批状态均是前置条件。）
- [x] 高风险和写操作不自动扩流；（风险等级或写副作用会固定选择 Current。）
- [x] 5% → 25% → 50% → 100% 每阶段按固定状态机逐级推进；（阶段转换代码拒绝跳级，观察窗口由 Release 控制面记录。）
- [x] 扩流需要质量、安全、E2E、成本和人工接管率全部通过；（`CanaryMetrics` 缺失即 fail closed，固定阈值由 `evaluate_canary()` 执行。）
- [x] 分桶稳定，用户同一会话不能在版本间来回跳变；（稳定 hash 不包含 Run ID，单测覆盖跨 Run 同会话稳定性。）
- [ ] 以上 Canary 门禁已用真实线上流量完成 5% → 25% → 50% → 100% 观察；（本地状态机和单测不替代真实流量证据。）
- [x] 候选版本必须先登记为 tenant-scoped active runtime；未登记时 assignment 固定 Current，发布评估拒绝晋级。

### 11.3 自动停止

新增 `src/release/canary_guard.py` 和 `scripts/check_canary.py`：

- [x] 任一 P0 安全事件立即停止；（`evaluate_canary()` fail closed。）
- [x] 终态回复覆盖率低于 100% 停止；（缺失覆盖率也停止，不按 0/100% 猜测。）
- [x] P95 E2E 高于基线 15% 或 P99 高于 25% 停止；（固定阈值由 `CanaryMetrics` 执行。）
- [x] 每成功 Run P95 成本高于基线 10% 停止；（未定价指标保持阻断/不晋级。）
- [x] 低风险误转人工率显著上升停止；（相对基线超过 20% 停止。）
- [x] Skill 跨 scope 命中或目标 slice 质量下降停止；（`CanaryMetrics` 增加 `skill_scope_violation` 与 `target_slice_quality_delta`，`evaluate_canary()` fail closed，单测覆盖两类停止原因。）
- [x] 停止只回滚到上一个已批准版本，不自动选择其他候选。（阶段决策返回 `rollback_version=current_version`，不自动挑选其他候选。）
- [x] `ENABLE_RELEASE_SCHEDULER=true` 时启动单进程观察调度器；只处理数据库中已结束的观察窗口，串行执行一次阶段评估并在 shutdown 时停止。

### 11.4 前端与报告

- [x] `GET /internal/v1/releases` 及详情接口返回阶段、流量、观察窗口、Gate、基线/候选版本和停止审计 DTO；（详情同时返回脱敏 release events 与 assignments。）
- [x] `/operations` 汇总质量、安全、时延、token、成本、路由、人工接管和 Skill 指标，并支持按版本对比；（`version_breakdown` 按发布 assignment 聚合运行指标，质量在无独立 Judge 标注时保持 `N/A`，Safety/人工接管按已落库事件统计；实现、前端回归和 PostgreSQL contract 见 `docs/plan/evidence/phase-n7-frontend-flow-observability-20260918.md`。）
- [x] `/releases/:id` 展示 Shadow → 5% → 25% → 50% → 100% 的发布进度、观察窗口、负责人和 Gate；（既有阶段/流量图加实时状态面板展示负责人、观察窗口、结构化 Gate、停止和回滚证据；`docs/plan/evidence/phase-n7-frontend-flow-observability-20260918.md`，前端构建与 7 个 Vitest 通过。）
- [x] 使用 current/candidate 对比图展示 route、response policy、Skill、质量、成本和时延 delta；（运营页和发布详情以 Current/Candidate 对比表/卡片展示，缺失线上聚合值保持 `N/A`；同一证据文档与前端回归覆盖。）
- [x] 控制台自动停止状态按 15 秒轮询刷新，并显示触发指标、阈值、回滚版本和审计事件；（`ReleaseLiveStatus` 保留上次成功快照并在刷新失败时显示部分状态。）
- [ ] 自动停止决定到线上新请求停止命中的传播在一分钟内完成；（仍需部署环境实测。）
- [x] Dashboard 卡片均可下钻到对应 Run、eval case、failure cluster 或 Skill，避免只有不可解释的聚合数字；运营页新增脱敏 Run 流程入口，评测、P0 Safety、失败簇、Skill 和 Release 页面保留现有资源链接；未授权的原文仍不下发。
- [x] 前端只展示脱敏摘要和统计，不展示原始 Prompt/纠错文本；（Run、评测、失败、Skill、Release 和运营下钻均使用白名单投影；纠错请求/展示边界由 `apps/web/src/ui/feedback.ts` 和 Vitest 覆盖。）
- [x] Markdown 发布报告包含当前/候选 delta 和自动停止状态。（`scripts/check_canary.py --markdown-report` 调用 `src/release/report.py`，缺失指标显示 `N/A`，并记录停止原因、Route/Policy/Skill 与时延/成本 delta；`tests/unit/test_check_canary.py` 覆盖。）
- [x] Release 创建、运行时注册、停止和评估接口均使用 Admin 认证与持久化幂等键；重复请求重放结构化结果，指纹冲突或并发处理中止。

### 11.5 验收门禁

- [x] Shadow 不改变用户可见结果和业务状态；（`assign_traffic()` 和路由/发布单测验证 Shadow 只记录观测。）
- [x] Canary 可稳定分桶、扩流和自动停止；（稳定桶位、逐阶段推进和 fail-closed stop 均有单测/契约；尚无真实线上流量证据。）
- [ ] kill switch 在一分钟内阻止新 Skill 命中；（控制面、逐请求读取和 fail-closed 回退已实现；仍需部署环境实测传播时延。）
- [x] 发布报告可以解释质量、风险、时延和成本变化；（`src/release/report.py` 增加 Gate details 表，逐项输出 P0、安全覆盖率、质量、P95/P99 时延、P95 成本、人工接管、Skill scope、阈值和 PASS/STOP/INCOMPLETE；`tests/unit/test_check_canary.py` 与相关 7 个测试通过。）
- [ ] 7 天基线完成后，将绝对 SLO 写回上位方案和运维手册；
- [x] 从运营总览可完整下钻“异常指标 → 失败簇 → 归因 → Skill → Canary/回滚”，且每个展示关联与状态来自租户隔离的后端审计投影；没有明确 assignment/不可变 ID 证据时显示“暂无可证明关联”。（`docs/plan/evidence/phase-n7-failure-learning-chain-20260918.md`；真实线上流量仍未宣称完成。）

## 12. 跨阶段测试命令

每阶段至少执行与变更相关的目标测试；阶段验收执行完整矩阵：

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce

python -m ruff check src tests scripts
python -m mypy src
python -m pytest -q

npm --prefix apps/web ci
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web test -- --run
npm --prefix apps/web run build

docker compose --profile maintenance run --rm migrate
scripts/deployment_smoke.sh
scripts/release_smoke.sh
```

需要 PostgreSQL 的 contract/recovery 测试使用隔离测试库，不触碰现有业务数据库。Live E2E 和 Judge 只在显式开关下调用外部模型，并记录成本。

## 13. 阶段完成证据模板

每个 Phase 完成后追加：

```text
Phase:
状态：completed / blocked
Commit SHA:
Migration head:
实现文件：
测试命令与结果：
评测报告：
安全检查：
时延/成本变化：
已知限制：
回滚方式：
```

## 14. 最终完成定义

- [x] 请求从受理到回复具备完整时延、token 和成本解释；（N1 的 Run visualization、运营聚合、Markdown 评测/发布报告和前端 Trace 均按 invocation 展示；缺失 usage/价格保持 `N/A`，对应 N1 验收与 `phase-n7-frontend-flow-observability-20260918.md`。）
- [ ] 低风险长尾不再无意义转人工；
- [x] 高危请求优先识别并安全降级；（Safety Router 位于普通路由之前，LiveCaseRuntime 和 synthetic hard gate 覆盖无模型/工具的安全降级；线上漏判率仍是独立未完成门禁。）
- [x] deterministic、live、synthetic、Shadow 和 Canary 报告严格区分；（评测报告记录 runtime/dataset/hash，发布报告独立记录 Current/Candidate 与自动停止状态，Shadow assignment 标记 `observation_only`。）
- [x] 用户反馈和失败信号可以进入可审计归因流程；（feedback/failure/signal/attribution API、审计和失败详情下钻已有单测与 contract 证据。）
- [x] Skill 只从至少 5 个不同来源的失败簇生成；（应用层和数据库侧均按独立 evidence identity 复核门槛。）
- [x] Skill 经离线评测、人工批准和 Canary 后生效；（paired evaluation、人工审批角色、生命周期状态机和 Canary API 均 fail closed；无人审批保持 `PENDING_REVIEW`。）
- [x] Skill 默认 tenant 隔离、TTL 30 天并具备受控回滚实现；（租户/Scope 隔离、默认 TTL、只回滚到上一个已批准版本均有代码与契约证据。）
- [ ] Skill 回滚在真实线上达到快速传播门槛；（一分钟内新请求不再命中仍需线上传播证据。）
- [x] 上线控制代码同时要求质量、安全、时延、成本和人工接管 Gate；（缺失指标 fail closed，并输出阈值/停止原因。）
- [ ] 真实线上上线记录同时满足并证明质量、安全、时延和成本 Gate；（当前没有真实 Canary/生产流量证据。）
- [x] 所有 internal 管理接口完成独立认证和审计；（Admin/Approver Bearer 边界、constant-time compare、幂等和审计测试已覆盖。）
- [ ] 用户侧与 internal 控制台均覆盖加载、空、部分、错误、断流、无权限和未知状态；（本轮已补 Run、评测、运营主接口的 `partial/forbidden` 语义及 SSE 断流提示；失败/Skill/Release 的部分刷新与部分接口失败状态仍需继续统一，且未知状态全页面审计尚未完成，故不提前勾选。）
- [ ] Run 流程、评测、失败、Skill 与发布页面能够互相下钻，且图表值与表格/Markdown 报告一致；
- [x] 前端不泄露 Prompt、思维链、密钥、未授权纠错文本或跨 tenant 数据；（服务端白名单投影、tenant 隔离、feedback consent 和前端 bundle/单测证据已覆盖。）
- [ ] 文档、迁移、测试和发布证据与实际实现一致。
