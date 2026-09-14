# 电商客服 Agent 分阶段实施与验收清单

> 版本：v2.5
>
> 日期：2026-09-14
> 执行者：Codex  
> 上位设计：[电商客服 Agent 技术设计方案](./feasibility-and-implementation-plan.md)  
> 当前整体状态：`in_progress`（Phase 0～1 已验收；Phase 2 因双执行器设计增量重新打开）

## 1. Codex 使用规则

本文档是实施时的顺序清单和阶段门禁，不再承担架构论证。数据模型、工具目录、状态机和 API 合同以上位设计为准；本文档负责说明“按什么顺序实现、如何验证、什么时候算完成”。

### 1.1 指令优先级

1. 当前用户明确指令；
2. [技术设计方案](./feasibility-and-implementation-plan.md)；
3. 本实施清单；
4. 代码内注释和历史实现。

下层内容与上层冲突时，不得静默偏离；应先修正设计/实施文档，再修改代码。

### 1.2 Checklist 语义

- `[ ]`：未完成，不得从文字描述推断为已完成。
- `[x]`：已实现且有对应的可重复验证证据。
- 阻塞项在对应 TODO 下新增 `BLOCKED:`，写明缺少的用户决策、外部系统或数据。
- 只有代码、测试、文档和运行验证都完成后，才能勾选阶段验收项。
- 不得为了让 checklist 变绿而放宽测试、修改评测金标或删除安全断言。
- TODO 的完成证据至少包含“变更文件 + 验证命令 + 结果/产物路径”；只创建空文件不算完成。
- 若用户在当前执行回合明确要求不运行测试，只更新文档或代码，不勾选依赖运行验证的项目；验证命令保留给后续执行。

### 1.3 阶段推进协议

Codex 执行每个阶段时必须：

1. 先读取本阶段的目标、依赖、TODO 和验收标准；
2. 检查工作区现状，保留用户已有变更；
3. 按垂直切片实现，一个切片同时包含协议、持久化、运行路径、trace 和测试；
4. 执行与变更风险匹配的验证；
5. 将已验证 TODO 和验收项改为 `[x]`；
6. 在第 14 章追加执行记录；
7. 在可独立验证的垂直切片和阶段验收完成后创建原子 Git commit，并记录 commit SHA；
8. 本阶段验收 checklist 未全部勾选时，不得声称阶段完成。

### 1.4 必须保持的约束

- AgentLoop、OrchestrationEngine、状态机、ToolRegistry、PolicyEngine 和 EvalHarness 全部由本项目实现。
- 代码主目录只使用 `src/`，不创建旧的包目录名。
- 模型只产生结构化 Decision，不直接执行工具、SQL、shell 或任意 HTTP。
- 意图分类器必须通过同一个 ModelGateway 复用主 Agent 模型；允许并要求配置 `CLASSIFIER_MODEL/CLASSIFIER_API_BASE/CLASSIFIER_API_KEY`，但三者必须与主 Agent 对应值相同，分类温度固定为 `CLASSIFIER_TEMPERATURE=0.1`。
- 只读请求进入有界 `AgentLoop.run()` while 循环；每轮只调用一次 `StepPipeline.advance()`：AgentStepExecutor 只产生单轮结果，StepPipeline 完成原子 checkpoint，AgentLoop 才能基于新 context 决定是否继续。
- `prepare/low_write/commit` 等写操作不得进入 AgentLoop，必须进入确定性 WorkflowExecutor。
- 写操作必须经过 `authenticate → prepare → confirm → commit → verify`。
- 未经 `StateVerified` 不得向用户声称写操作成功。
- 评测固定使用 300 个静态 case，不调用 user simulator。
- Rubric Judge 不得覆盖 hard fail。
- 不在 prompt、trace、前端 bundle、日志或版本库中写入密钥和未脱敏 PII。
- 当前服务器不部署本地 LLM、Redis、独立前端容器或重型监控套件。

## 2. 固定技术基线

| 区域 | 固定决定 |
|---|---|
| 后端 | Python 3.12.x、FastAPI 0.116.x、Uvicorn 0.35.x、Pydantic 2.11.x |
| 持久化 | PostgreSQL 18.6、SQLAlchemy Core 2.0.x、psycopg 3.2.x、Alembic 1.16.x |
| 模型调用 | 自研 ModelGateway + HTTPX 0.28.x；Classifier 使用独立变量名但值与主 Agent 模型/端点/Key 相同，温度固定 0.1；Judge 使用独立配置 |
| 前端 | React 19.1.x、TypeScript 5.8.x、Vite 7.x、CSS Modules、原生 fetch/EventSource |
| 质量工具 | pytest + Ruff + mypy；Vitest + ESLint + `tsc --noEmit` |
| 运行 | Docker multi-stage build + Docker Compose |
| 服务拓扑 | `app` 384 MiB + `db` 256 MiB，总上限 640 MiB |
| 端口 | 宿主 `127.0.0.1:18437` 映射容器 `8000`；DB 仅内部网络 |
| RAG | PostgreSQL metadata filter + `pg_trgm` + 应用内排序；dense retrieval 默认关闭 |
| 评测 | 自研 EvalHarness；硬判分 + Rubric Judge；默认并发 1；release 使用独立 Judge |

实现时将确切 patch 版本锁定到 `pyproject.toml` 和 `apps/web/package-lock.json`。未经用户请求，不在实施过程中重新选型。

## 3. 已有输入与初始状态

### 3.1 已具备资产

- [x] Git 仓库已初始化，默认分支为 `main`，已有可追溯提交基线。
- [x] Conda 环境 `commerce` 已创建，Python 版本为 3.12.x。
- [x] Agent/Judge 模型配置保存在项目根目录 `.env`，且 `.env` 已被 Git 忽略；这里只确认配置位置，不记录配置值。
- [x] 技术设计文档：[`docs/plan/feasibility-and-implementation-plan.md`](./feasibility-and-implementation-plan.md)。
- [x] 目标参考图：[`docs/plan/image.png`](./image.png)。
- [x] 300 条静态 case：[`evals/commerce_bench_zh/cases.jsonl`](../../evals/commerce_bench_zh/cases.jsonl)。
- [x] 13 条知识证据：[`evals/commerce_bench_zh/knowledge.jsonl`](../../evals/commerce_bench_zh/knowledge.jsonl)。
- [x] Rubric 配置：[`evals/commerce_bench_zh/rubrics.json`](../../evals/commerce_bench_zh/rubrics.json)。
- [x] Judge prompt：[`evals/commerce_bench_zh/JUDGE_PROMPT.md`](../../evals/commerce_bench_zh/JUDGE_PROMPT.md)。
- [x] 数据说明、来源与许可：[`README.md`](../../evals/commerce_bench_zh/README.md)、[`SOURCES.md`](../../evals/commerce_bench_zh/SOURCES.md)、[`LICENSE-DATA.md`](../../evals/commerce_bench_zh/LICENSE-DATA.md)。
- [x] 固定来源下载和校验脚本：[`scripts/download_eval_sources.py`](../../scripts/download_eval_sources.py)。
- [x] 确定性数据构建脚本：[`scripts/build_static_eval_dataset.py`](../../scripts/build_static_eval_dataset.py)。

### 3.2 当前实现基线与缺口

- [x] Phase 0 已完成 Python/API、React/Vite、Docker/Compose 与最小 conversation 骨架，并通过本机 deployment smoke。
- [x] Phase 1 已完成核心协议、PostgreSQL migration/repository、原子 checkpoint、事件回放和 Eval Core。
- [x] Phase 2 v2.2 已完成单步 `run_step()`、ModelGateway、工具/政策边界与最小 hard-eval Harness；这只是双执行器改造的输入基线。
- [ ] 完成 Phase 2 v2.5：拆分 AgentStepExecutor，新增真正的有界 `AgentLoop.run()`、复用主模型且温度为 0.1 的意图分类器、WorkflowExecutor、执行模式约束和多轮 Harness。
- [ ] 完成 Phase 3 的只读业务 adapter、RAG、完整对话 API/SSE、Trace UI；当前 React 页面只是工程骨架。
- [ ] 完成 Phase 4～6 的事务 workflow、Rubric Judge/300-case 完整报告、安全恢复和运维硬化。
- [ ] 完成 Phase 7 的全链路验收并生成 internal beta 发布证据。

## 4. 阶段总览

| 阶段 | 状态 | 核心产物 | 硬门禁 |
|---|---|---|---|
| Phase 0：可运行工程骨架 | `completed` | app/web/db/Compose/最小 conversation 闭环 | 目标机可启动、ready、重启不丢 conversation |
| Phase 1：协议、持久化与 Eval Core | `completed` | 核心 schema、repository、case loader、hard evaluator | 原子 checkpoint、租户隔离、数据合同测试通过 |
| Phase 2：自研 Runtime 与最小 Harness | `in_progress` | ModelGateway、有界 AgentLoop、WorkflowExecutor、编排、工具/政策、hard runner | 多轮循环可终止/恢复，写动作不能进入自由循环，分 track hard eval 可执行 |
| Phase 3：只读业务与对话页 | `not_started` | RAG、商品/订单查询、SSE、Trace UI | 三个只读场景可展示，无越权/无证据编造 |
| Phase 4：事务 workflow | `not_started` | prepare/confirm/commit/verify 与确认卡 | 未确认、重放、跨账号和重复写入均为 0 |
| Phase 5：评测 Harness 完整化与面板 | `not_started` | Judge、持久化报告、三次运行、报告 UI | forbidden tool 为 0，Judge 不改写 hard fail |
| Phase 6：安全、恢复与运维硬化 | `not_started` | 故障注入、数据保护、降级、备份 | P0 安全/恢复断言全通过 |
| Phase 7：全链路验收 | `not_started` | 候选版本、正式报告、运行手册 | 所有阶段 checklist 完成，明确标记 internal beta |

```text
Phase 0 工程骨架
  → Phase 1 协议/持久化/Eval Core
  → Phase 2 Runtime/最小 Harness
  → Phase 3 只读业务/UI
  → Phase 4 事务 workflow/UI
  → Phase 5 EvalHarness/UI
  → Phase 6 安全与运维
  → Phase 7 发布验收
```

## 5. Phase 0：可运行工程骨架

### 5.1 目标与依赖

目标：不实现 Agent 业务逻辑，先建立可构建、可迁移、可启动、可打开页面的最小闭环。

依赖：无。

### 5.2 实现 TODO checklist

工程结构：

- [x] 创建 `pyproject.toml`，锁定 Python 3.12 及后端依赖。
- [x] 创建 `src/`、`apps/api/`、`apps/worker/`、`apps/web/` 和 `tests/` 包结构。
- [x] 创建 `apps/web/package.json`、`apps/web/package-lock.json`、TypeScript/Vite 配置和 CSS Modules 入口。
- [x] Git 仓库和 `.gitignore` 已存在，`.env` 已被忽略。
- [x] 补齐 `.gitignore`：Python/Node 缓存、前端构建目录、测试覆盖率、`evals/reports/`、soak PID/状态文件和本地数据库产物；保留可提交的 `docs/releases/`。
- [x] 创建 `.env.example`，只包含变量名和非敏感默认值。
- [x] 明确 `src` 为 Python 顶层包并加入 `src/__init__.py`，所有命令统一使用 `python -m src...`。
- [x] 配置 pytest、Ruff、mypy、Vitest、ESLint 和 TypeScript typecheck，并在 `docs/runbooks/local-development.md` 固定命令。
- [x] 定义开发环境 bootstrap：激活 `commerce`、校验 Python 3.12、执行 `python -m pip install -e ".[dev]"` 和 `npm ci --prefix apps/web`。
- [x] 实现 `scripts/check_secrets.py` 并执行密钥卫生 preflight：`.env` 权限为 `0600`、清除工作区注释中的凭据字面量、Git tracked files/镜像/前端产物扫描通过；扫描结果不得输出密钥值。`.env` 只做权限、变量名和注释策略检查，不把预期存在的密钥值当成仓库泄漏。
- [x] 检查 Git 历史是否含凭据；若命中，立即停止、轮换凭据并请求用户决定历史清理方案，不得擅自重写历史。

应用与前端：

- [x] 实现 FastAPI 应用工厂和 `/health/live`。
- [x] 实现 `/health/ready`，初版检查 DB 连通和 migration 版本。
- [x] 实现最小 `conversation.conversations` 表、`ConversationRepository.create/list` 和 `POST/GET /v1/conversations`，专用于可复用的 deployment smoke。
- [x] 实现 React 三个空路由：`/`、`/runs/:runId`、`/evals`。
- [x] 实现三栏响应式页面壳，小屏将两侧栏收起为 drawer。
- [x] Vite 构建产物由 FastAPI 同源托管，任意前端路由刷新均回退到 `index.html`。

数据库与部署：

- [x] 创建 Alembic 基线 migration，创建七个 PostgreSQL schema 和最小 `conversation.conversations` 表。
- [x] migration 中创建 `pg_trgm`，失败时 ready 不通过。
- [x] 创建 multi-stage `Dockerfile`：Node 22 builder + Python 3.12 runtime。
- [x] 创建 `compose.yaml`，只含 `app` 和 `db` 默认服务。
- [x] `app` 限制 384 MiB/1.5 CPU，`db` 限制 256 MiB/0.75 CPU。
- [x] DB volume 挂载到 `/var/lib/postgresql`，不使用旧版 data 挂载点。
- [x] 宿主只暴露 `127.0.0.1:18437`，PostgreSQL 不映射宿主端口。
- [x] 应用使用非 superuser runtime 账号，migration 权限与 runtime 权限分离。
- [x] 提供幂等 DB bootstrap：管理账号只负责创建 migration/runtime 角色；migration 使用 `DATABASE_MIGRATION_URL`，应用只使用受限 `DATABASE_URL`。
- [x] Compose 的 `db` 服务只用 `POSTGRES_USER/POSTGRES_PASSWORD` 初始化 admin；app 不接收 admin 凭据，只接收 `DATABASE_URL`，migration 命令只接收 `DATABASE_MIGRATION_URL`。
- [x] 用 GRANT/默认权限限制 runtime 只能对必要表执行 DML，不能执行 DDL、创建扩展或访问其他 schema。
- [x] 固定 PostgreSQL 首版参数：`shared_buffers=64MB`、`work_mem=2MB`、`max_connections=20`、`statement_timeout=10s`。

### 5.3 验证命令

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce
python --version
python -m pip install -e ".[dev]"
npm ci --prefix apps/web
python -m ruff check src tests
python -m mypy src
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
python scripts/check_secrets.py --repository . --tracked-only --env-policy .env --frontend apps/web/dist
python scripts/check_secrets.py --git-history --redact
docker compose config --quiet
docker compose build
python scripts/check_secrets.py --compose-service app
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:18437/health/live
curl -fsS http://127.0.0.1:18437/health/ready
scripts/deployment_smoke.sh
```

`scripts/deployment_smoke.sh` 必须通过 `POST /v1/conversations` 创建带唯一 `client_request_id` 的 smoke conversation，执行 `docker compose restart`，再通过 `GET /v1/conversations` 确认同一记录仍存在；重复执行不得产生重复记录。不使用 `docker compose down -v`。

### 5.4 验收 checklist

- [x] 新环境只需 `.env` 即可构建和启动。
- [x] `live` 和 `ready` 返回 200，DB/migration 失效时 `ready` 不返回假成功。
- [x] `/`、`/runs/demo`、`/evals` 都能打开空页壳。
- [x] 容器总内存上限为 640 MiB，没有 Redis/Node/Nginx 运行容器。
- [x] DB 重启后数据保留，卷挂载点正确。
- [x] migration 账号可前向迁移；runtime 账号不能执行 DDL、创建扩展或跨 schema 越权访问。
- [x] 镜像、前端 bundle 和日志中不含 `.env` 密钥。
- [x] `commerce` 环境和前后端依赖可由 bootstrap 命令重复建立，lint/typecheck 均通过。
- [x] Phase 0 完成后创建原子 commit，并在执行记录中保存 commit SHA 和 clean worktree 证据。
- [x] Phase 0 所有 TODO 均已勾选。

### 5.5 阶段产物

- `pyproject.toml`、`apps/web/package.json`、`apps/web/package-lock.json`
- `Dockerfile`、`compose.yaml`、`.env.example`
- FastAPI/React 最小应用
- Alembic 基线 migration、DB 角色 bootstrap、最小 conversation slice
- `scripts/deployment_smoke.sh`
- `scripts/check_secrets.py`
- `docs/runbooks/local-development.md`

## 6. Phase 1：核心协议、持久化与 Eval Core

### 6.1 目标与依赖

目标：实现 Runtime、workflow 和 EvalHarness 共用的强类型协议，将数据库逻辑 Schema 落成 PostgreSQL migration/repository，并前置不依赖 Runtime 的 case loader 与 hard evaluator，解除后续阶段的评测循环依赖。

依赖：Phase 0 验收完成。

### 6.2 实现 TODO checklist

协议：

- [x] 实现 `RunContext`、`SlotValue`、`PromptView` 和 `StatePatch`。
- [x] 实现 `Decision`、`Step`、`StepResult` 和严格枚举。
- [x] 实现 `ToolSpec`、`ToolContext`、`ToolResult`、`ToolError`。
- [x] 实现 `DomainEvent`、`EventEnvelope` 和事件 payload 版本。
- [x] 实现 workflow/policy 版本引用和不可变定义。
- [x] 对所有协议禁止未知字段，对外 JSON 含 `schema_version`。

数据库：

- [x] 在 Phase 0 的 conversations 表上补齐索引/约束，并实现 messages migration。
- [x] 为 `runtime` 实现 runs/checkpoints/events/model/tool/confirmation/idempotency/outbox migration。
- [x] 为 `domain/memory/knowledge/evaluation/audit` 实现对应 migration。
- [x] 将逻辑 `VARCHAR(36)/TIMESTAMP/JSON` 映射为 `uuid/timestamptz/jsonb`。
- [x] 实现主键、外键、唯一约束、部分唯一索引和租户索引。
- [x] 实现同一 conversation 最多一个非终态 run 的数据库约束。

Repository 与事务：

- [x] 实现 `RunRepository`、`ConversationRepository`、`ConfirmationRepository`、`EvaluationRepository`。
- [x] 实现 `MemoryRepository`、`KnowledgeRepository`、`AuditRepository`，并保持接口与物理 SQL 分离。
- [x] 所有业务读写入口强制要求 `tenant_id`，禁止业务层拼接 SQL；仅 EvalHarness、版本发布和 outbox worker 为 system-scope，不提供用户资源的无范围读取接口。
- [x] 实现“事件 + checkpoint + run 行版本”的单事务提交。
- [x] 实现 confirmation token 条件消费与 idempotency record 同事务。
- [x] 实现 outbox 租约，使用 `FOR UPDATE SKIP LOCKED`。
- [x] 实现 schema migration 版本检查和 checkpoint state migration 接口。

Eval Core：

- [x] 实现 `EvalCase`、`ExpectedOutcome`、`NormalizedTrace` 和 hard-eval result schema。
- [x] 实现 `CaseLoader`：JSONL/schema、track/ID 过滤、总数/分轨计数和 dataset hash；禁止运行时静默修复 case。
- [x] 实现五个 track 的纯函数 hard evaluator，并用独立 golden pass/fail fixtures 验证判分器自身。
- [x] 对 300-case 生成语义审核清单：逐项检查 intent/route、60 个 workflow 参数、50 个 RAG 证据可推出性、20 个 clarification 槽位和 20 个 guardrail forbidden tools。
- [x] 将审核结论、修订原因、数据版本和冻结 hash 写入 `evals/commerce_bench_zh/quality-audit.md`；数据修订必须单独 commit。

### 6.3 验证命令

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce
python -m pytest tests/unit/test_protocols.py
python -m pytest tests/contract
python -m pytest tests/harness/test_loader.py tests/harness/test_hard_eval.py tests/harness/test_dataset_contract.py
```

### 6.4 验收 checklist

- [x] 所有核心对象可序列化/反序列化，非法枚举和未知字段被拒绝。
- [x] 全新 DB 可从空库前向迁移到 head。
- [x] 所有表在正确 PostgreSQL schema 中，约束/索引与设计文档一致。
- [x] checkpoint 事务在任何一步失败时不产生部分状态。
- [x] 同一 run 并发更新只有一个成功，另一个收到版本冲突。
- [x] 跨租户 repository 读写返回空/拒绝，不泄露资源是否存在。
- [x] confirmation/idempotency 唯一约束能阻止重放。
- [x] CaseLoader 恰好加载 300 条，五个 track 为 150/60/50/20/20，schema/ID/hash 异常均 fail closed。
- [x] golden pass/fail fixtures 被 hard evaluator 100% 正确判断。
- [x] 300-case 语义审核有逐轨证据和冻结 hash，不能只以 JSON 可解析代替质量审核。
- [x] Phase 1 完成后创建原子 commit，并记录 commit SHA 和 clean worktree 证据。
- [x] Phase 1 所有 TODO 和验证命令均完成。

### 6.5 阶段产物

- `src/orchestration/context.py`、`step.py`、`events.py`
- `src/agent/decision.py`、`src/tools/spec.py`
- `src/storage/` repository 实现
- `src/harness/schema.py`、`loader.py`、`hard_eval.py`
- `infra/migrations/` 全量基础 migration
- `evals/commerce_bench_zh/quality-audit.md`
- 协议、migration、repository、事务、租户隔离和 Eval Core 测试

## 7. Phase 2：自研 Agent Runtime 与最小 Harness

### 7.1 目标与依赖

目标：用 fake model/fake tools 完整验证双执行器语义：只读请求由有界 `AgentLoop.run()` 在 `while` 中自动推进多个单步，写请求由确定性 WorkflowExecutor 推进；再连接真实模型 API，并交付能按 track 驱动 Runtime 到暂停或终态的最小 hard-eval Harness，供 Phase 3/4 使用。

依赖：Phase 1 验收完成。

### 7.2 实现 TODO checklist

ModelGateway：

- [x] 实现 `.env` 配置读取，不记录 `API_KEY`。
- [x] 实现 OpenAI-compatible HTTP 请求、timeout、限次重试和错误归一化。
- [x] 固定 Agent model、temperature、token limit、timeout、retry 和 prompt hash，并把配置指纹写入 run/model invocation。
- [x] 实现结构化 Decision 解析；不合法输出只修复一次。
- [x] 实现 `model_invocations` 脱敏记录，不保存隐藏思维链。
- [x] 提供 deterministic fake model，覆盖所有 Decision 分支。
- [ ] 在同一 ModelGateway 增加 `purpose=intent_classification` profile，从 `CLASSIFIER_MODEL/CLASSIFIER_API_BASE/CLASSIFIER_API_KEY` 读取显式配置，并校验其值与主 Agent 对应配置相同。
- [ ] 为分类 profile 固定独立的 `RoutingPromptView`、`IntentClassification` Schema、`temperature=0.1`、输出 token 上限、Prompt/Schema 哈希，并在 `model_invocations` 记录 `purpose` 与脱敏延迟。
- [ ] 更新 `.env.example` 和配置 Schema，加入四个 `CLASSIFIER_*` 变量；Demo/production 缺失、三项连接配置不相等或温度不是 0.1 时，`/health/ready` 必须失败且错误不得泄露配置值。
- [ ] 提供 deterministic fake intent classifier，覆盖只读、写、低置信度、未知意图和模型输出不合法路径。

工具与政策：

- [x] 实现不可变 `ToolRegistry`，按 `name + version` 注册。
- [x] 实现 `DecisionValidator`：schema、route、step、allowlist、risk、system-field 检查。
- [x] 实现 `ToolExecutor`：owner/scope/policy/deadline、adapter 调用、结果 schema、脱敏、trace。
- [x] 实现版本化 `PolicyEngine`，只允许白名单事实/操作符。
- [x] 实现错误分类：只读可重试一次，commit 状态未知不重试。
- [x] 提供 fake tool adapter，覆盖成功、拒绝、超时、冲突和 unknown。

Loop 与编排：

- [x] 已有 `AgentLoop.run_step()` 单步基线，一步最多一个动作。
- [x] 固化 `build_prompt → request_decision → validate → execute → observe → reduce → checkpoint → terminate` 顺序。
- [x] 在单步入口实现 `max_steps=6`、deadline、token budget 和 cancellation checks。
- [x] 实现 `OrchestrationEngine.create/advance/resume/cancel`。
- [x] 实现 `WorkflowRegistry` 和版本锁定，已发布版本不可原地修改。
- [x] 实现设计文档第 5.1 节全部 run 状态和非法跳转拒绝。
- [x] 实现每 step 原子 checkpoint、崩溃恢复和事件回放。
- [x] 实现 `TraceStore`，只保留结构化决定和脱敏 observation。
- [x] Runtime 注册完成后扩展 `/health/ready`：检查 Tool/Workflow/Policy registry 完整性和模型配置是否存在，但不调用模型。
- [ ] 将现有 `AgentLoop.run_step()` 单轮职责迁移/重命名为 `AgentStepExecutor.execute_step()`，并保持兼容入口只作为过渡，不允许出现两套单步实现。
- [ ] 实现 `AgentLoop.run()` 有界 `while` 主循环；循环必须使用每轮 checkpoint 返回的新 `RunContext`，不得反复使用旧 context。
- [ ] 每轮只调用一次 `StepPipeline.advance()`；只有八阶段全部完成且 checkpoint 已提交、状态仍为 `running_readonly` 时才能进入下一轮。
- [ ] 每轮重新构建 PromptView，使第 N 轮脱敏 observation 成为第 N+1 轮的可信输入；禁止把 adapter 原始结果直接拼入 prompt。
- [ ] 在每轮开始、模型返回后、工具调用前和进入下一轮前检查 cancellation、绝对 deadline、`max_steps` 与 token budget；usage 缺失时按保守上界扣减。
- [ ] 实现循环无进展检测：连续等价 Decision/工具参数或重复只读错误达到上限后安全退出，禁止空转到 deadline。
- [ ] 定义强类型 `RouteDecision(outcome=execute | handoff)`：execute 必须选择并持久化 `execution_mode=readonly_loop | workflow`；handoff 直接进入 `waiting_human` 且不能作为 execution_mode 持久化。
- [ ] 实现 `IntentClassification → RouteDecision` 代码复核：模型只给候选意图/风险/route，最终 execution_mode 由固定 intent 映射、置信度阈值和 ToolSpec.risk 决定。
- [ ] 新增双执行器协议、数据库 migration 和 repository 约束：created/routing/直接 handoff 允许 execution_mode/workflow 为空；选定后不可修改；run 状态与 execution_mode 必须满足设计文档第 6.4 节 CHECK。
- [ ] 实现执行器选择与模式防火墙：AgentLoop 只接受 `read_only` 工具，任何 `prepare/low_write/commit` Decision 在副作用前拒绝并进入 `waiting_human`；同一 run 禁止原地切换 execution_mode，真正的写请求由可信 Router 创建/选择 workflow run。
- [ ] 实现 Readonly loop 的暂停/恢复：`waiting_user/waiting_human` 立即退出；恢复时从最新 checkpoint 和创建时锁定的 model/prompt/workflow/policy/tool 版本重新进入。
- [ ] 重构依赖方向为 `OrchestrationEngine → AgentLoop → StepPipeline → AgentStepExecutor`；禁止 StepPipeline/AgentStepExecutor 反向调度 OrchestrationEngine，避免递归和双重 checkpoint。
- [ ] 实现 WorkflowExecutor 入口合同；写流程只按版本化转移表推进，不复用 AgentLoop 的自由 `while` 控制流。

最小 Harness：

- [x] 实现 `FixtureManager`、`RunDriver` 和 `TraceAdapter`，每个 case 使用隔离 mock 状态并输出 Phase 1 定义的 `NormalizedTrace`。
- [x] 实现 `src.harness.runner` 的 `--track/--case-id/--judge off/--timeout` 参数、失败隔离、取消和确定性 JSON 报告。
- [x] 最小 Harness 只执行 hard eval，不包含 Judge、批次持久化或 Web 面板；这些能力在 Phase 5 完成。
- [x] 添加 opt-in live ModelGateway smoke：仅检查真实端点认证、结构化 Decision、错误归一化和延迟，不输出 request header、密钥或完整 payload。
- [ ] 将 `RunDriver` 从“只驱动一个 `run_step()`”升级为驱动 `AgentLoop.run()` 到暂停/终态；fixture 支持多轮 Decision 和多次只读工具 observation。
- [ ] 增加至少一条 `tool A → observation A → tool B → observation B → finish` 的 deterministic case，并证明 Runtime 仍看不到 expected/source/forbidden/track。

### 7.3 验证命令

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce
python -m pytest tests/unit
python -m pytest tests/unit/test_classifier_settings.py tests/unit/test_intent_classifier.py tests/unit/test_route_decision.py
python -m pytest tests/workflow/test_readonly_loop.py
python -m pytest tests/workflow/test_bounded_readonly_loop.py tests/workflow/test_executor_routing.py
python -m pytest tests/recovery/test_readonly_loop_resume.py
scripts/run_phase1_contract_tests.sh tests/contract/test_dual_executor_routing.py
scripts/run_phase1_contract_tests.sh tests/recovery/test_postgres_checkpoint_recovery.py tests/recovery/test_postgres_event_replay.py tests/recovery/test_postgres_mutation_recovery.py
python -m pytest tests/harness/test_deterministic_runtime.py tests/harness/test_run_driver.py tests/harness/test_runtime_adapter.py tests/harness/test_runner.py
python -m pytest tests/harness/test_multistep_runtime.py
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --track intent_route --judge off
RUN_LIVE_MODEL_TEST=1 python -m pytest -m live tests/integration/test_model_gateway_live.py
RUN_LIVE_MODEL_TEST=1 python -m pytest -m live tests/integration/test_intent_classifier_live.py
```

### 7.4 验收 checklist

- [x] 非 JSON、未知 type、未知 tool、多工具和系统字段入参均在副作用前被拒绝。
- [x] 一个 step 最多执行一个工具，达到步数/deadline 后必定终止。
- [x] 只读超时最多重试一次，写操作 unknown 绝不盲目重试。
- [x] 同一 run 并发 advance 只有一个成功。
- [x] 在 checkpoint 前/后注入崩溃，恢复后事件和工具副作用不重复。
- [x] 旧 run 在 workflow v2 发布后仍使用创建时锁定的 v1。
- [x] Trace 不含密钥、确认 token 明文、完整 PII 或隐藏思维链。
- [x] fake model/fake tools 可跑通 complete、wait_user、wait_human、fail 和 cancel 路径。
- [x] 最小 Harness 能筛选 case/track、隔离 fixture、驱动 Runtime 并生成 hard-eval JSON。
- [x] 真实模型 smoke 返回合法 Decision 并记录脱敏的模型版本与延迟。
- [ ] 分类调用与 Agent 决策调用解析到相同的 endpoint、model 和 API Key；分类配置使用独立变量名，温度恰好为 0.1，差异仅限 `purpose/prompt/schema/采样参数`。
- [ ] Classifier 与 Agent 的模型、端点或 Key 任一不相等，或 `CLASSIFIER_TEMPERATURE != 0.1` 时，readiness fail closed；日志、trace 和错误响应不包含配置原值。
- [ ] 模型候选 route 与代码风险映射或 ToolSpec.risk 冲突时，以更高风险路径为准；低置信度/未知意图不进入任一自动执行器。
- [ ] `AgentLoop.run()` 能连续执行至少两个只读工具调用，并让后一轮模型看到前一轮的脱敏 observation，最终自动到达 `completed`。
- [ ] `waiting_user/waiting_human/completed/failed/cancelled/expired` 均立即退出 while，不发生额外模型或工具调用。
- [ ] `max_steps/deadline/token budget/cancellation/无进展` 任一门禁触发后均有限终止，且最终状态和事件已 checkpoint。
- [ ] AgentLoop 遇到 `prepare/low_write/commit` 工具建议时副作用次数为 0；相同请求由 WorkflowExecutor 按确定性节点处理。
- [ ] 数据库拒绝 run 状态与 execution_mode 不匹配、`handoff` 作为 execution_mode，以及执行器/workflow 版本在选定后的修改。
- [ ] 在相邻两轮 checkpoint 前后注入崩溃，恢复后从最新已提交 context 继续，不跳步、不重复持久化事件。
- [ ] 多步 Harness 驱动的是 `AgentLoop.run()` 而不是测试专用伪循环，并输出完整的 step/tool/termination trace。
- [ ] Phase 2 双执行器增量完成后创建原子 commit，并记录 commit SHA 和 clean worktree 证据。
- [ ] Phase 2 v2.5 所有新增 TODO 和验证命令均完成。

### 7.5 阶段产物

- `src/models/`、`src/agent/`、`src/orchestration/`
- `src/agent/loop.py` 的有界 `run()`、`src/agent/step_executor.py` 的单轮执行、`src/agent/intent_classifier.py` 的主模型分类 profile
- `src/orchestration/router.py` 的代码风险复核，以及 `src/orchestration/workflow_executor.py`
- `src/tools/registry.py`、`executor.py`
- `src/policies/engine.py`
- `src/telemetry/trace.py`
- `src/harness/runtime.py`、`deterministic_runtime.py`、`run_driver.py`、`runner.py`
- Runtime 单元、workflow、recovery 和 security 测试
- 最小 hard-eval Harness 报告与脱敏 live ModelGateway smoke 证据

## 8. Phase 3：只读业务、API 与对话页

### 8.1 目标与依赖

目标：完成 FAQ/政策、商品详情/对比、订单/物流查询三类可展示的只读链路。

依赖：Phase 2 v2.5 双执行器与主模型分类器增量验收完成。

### 8.2 实现 TODO checklist

业务与 RAG：

- [ ] 在 Phase 2 Router 上配置 30 个核心电商 intent 的代码映射、置信度阈值和 required slots；分类调用继续复用主 Agent 模型，不增加第二模型。
- [ ] 实现 slot extractor，订单号/商品号在 owner 校验前只是 unverified。
- [ ] 实现 `knowledge.jsonl` 确定性 ingestion 和版本 hash。
- [ ] 实现 tenant/access/effective-time/status metadata 强过滤。
- [ ] 实现 Unicode 2/3-gram + `pg_trgm` 候选检索和应用内排序。
- [ ] 实现 `EvidencePack`、evidence ID 引用和证据不足拒答。
- [ ] 实现 `search_catalog/get_product_detail/compare_products/retrieve_knowledge`。
- [ ] 实现 `list_my_orders/get_order_status/get_delivery_tracking/get_payment_status/get_refund_status`。
- [ ] 提供固定 catalog/order/delivery/payment/refund fixtures，不依赖真实业务 API。
- [ ] 价格、库存、订单和退款状态只来自结构化工具，不从 RAG 旧快照返回。

Memory：

- [ ] 实现会话短期 memory：已认证主体、目标、槽位、证据/工具结果引用和未完成 workflow 指针。
- [ ] 实现受控长期 memory：只保存经授权的稳定偏好，包含来源、时间、TTL、置信度和覆盖关系。
- [ ] 禁止将订单、支付、退款状态或模型推测写入长期 memory。
- [ ] 实现长期 memory 的更新、冲突处理、过期过滤和用户删除接口。

API 与 SSE：

- [ ] message API 根据可信 `execution_mode` 调用 `AgentLoop.run()` 或 WorkflowExecutor；只读 loop 持续执行到等待/终态，不能只执行一轮后静默返回。
- [ ] SSE 对每轮已提交 checkpoint 发布结构化进度；客户端断线不能取消服务端循环，重连后按事件 ID 回放。
- [ ] 扩展 Phase 0 的 `POST/GET /v1/conversations` 为完整 actor/分页合同，并实现 `GET/POST /v1/conversations/{id}/messages`。
- [ ] 实现 `GET /v1/runs/{run_id}` 和脱敏 `GET /v1/runs/{run_id}/events`。
- [ ] 实现 SSE 事件 ID、heartbeat、`Last-Event-ID` 续传和 run 回读恢复。
- [ ] message API 使用 `client_message_id`/`Idempotency-Key` 去重。
- [ ] 只从服务端 demo actor allowlist 注入 actor/tenant/scope。
- [ ] 实现 `GET /internal/v1/demo/scenarios`；`DEMO_MODE=false` 时路由不可用。

前端：

- [ ] 实现左侧会话/预置场景、中间消息流、右侧 Trace 抽屉。
- [ ] 实现消息发送、流式状态、错误重试、取消与空状态。
- [ ] 实现 evidence 引用卡，显示来源、版本和脱敏片段。
- [ ] 实现 run 状态条和事件时间线，不显示隐藏思维链。
- [ ] 页面刷新后重新读取 conversation/messages/run，不把本地状态当业务真值。
- [ ] 在 960 px 以下将左右栏收起为 drawer，确保键盘焦点和基本无障碍标签。

### 8.3 验证命令

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce
python -m pytest tests/unit/rag tests/contract/tools/test_readonly_tools.py
python -m pytest tests/workflow/test_faq.py tests/workflow/test_product_compare.py tests/workflow/test_order_query.py
python -m pytest tests/security/test_resource_owner.py tests/security/test_rag_acl.py
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --track intent_route --judge off
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --track rag_grounding --judge off
```

### 8.4 验收 checklist

- [ ] FAQ/政策回答带有效 evidence ID，无证据时不编造。
- [ ] 商品对比仅使用对齐后的结构化字段和当前证据。
- [ ] 订单/物流查询强制 owner + tenant，跨账号工具调用为 0。
- [ ] 三个预置场景可从 Web 首页完整走通。
- [ ] 至少一个只读预置场景在单次 run 中完成两次工具调用后自动回答，证明前端/API 接入的是真正多轮 AgentLoop。
- [ ] SSE 中断并重连后无丢事件、无重复消息；失败时能回读 run。
- [ ] 页面刷新后会话与最终状态恢复。
- [ ] Trace UI 只显示脱敏事件、工具和规则摘要。
- [ ] 长期 memory 仅包含允许的稳定偏好，过期/删除后不再进入 `PromptView`。
- [ ] 150 个 intent case 的 intent/route exact match ≥ 90%。
- [ ] 50 个 RAG case 必要事实覆盖率 ≥ 90%，evidence ID 精度 ≥ 95%。
- [ ] Phase 3 指标由 Phase 2 的最小 Harness 生成，报告记录 dataset/runtime/prompt hash。
- [ ] Phase 3 完成后创建原子 commit，并记录 commit SHA 和 clean worktree 证据。
- [ ] Phase 3 所有 TODO 和验证命令均完成。

### 8.5 阶段产物

- `src/rag/`、`src/workflows/faq.py`、`catalog.py`、`order_query.py`
- `src/tools/adapters/mock/` 只读 fixtures/adapters
- conversation/run/events/SSE API
- `apps/web` 对话工作台和 run Trace 页
- 只读业务、越权、RAG grounding 和前端测试

## 9. Phase 4：确定性事务 Workflow

### 9.1 目标与依赖

目标：用 mock 业务系统实现取消、修改地址、退款、退货和换货，所有副作用均由状态机执行。

依赖：Phase 3 验收完成。

### 9.2 实现 TODO checklist

通用事务协议：

- [ ] 实现 `authenticate/load_resource/check_eligibility/collect_slots/prepare/confirm/commit/verify`。
- [ ] 所有 mutation route 显式选择 `execution_mode=workflow`；任何路径都不能把 write ToolSpec 交给 `AgentLoop.run()`。
- [ ] 为取消、地址、退款、退货、换货发布独立 workflow version。
- [ ] 实现 prepare preview：操作、资源、商品、数量、金额/差价、渠道、时效、政策版本。
- [ ] confirmation token 绑定 actor、tenant、resource、mutation、args、preview、policy/workflow 版本和过期时间。
- [ ] 只接受明确确认；“随便/应该可以/先这样”不消费 token。
- [ ] 任一参数、preview 或版本变化后立即作废旧 token，重新 prepare。
- [ ] 实现幂等预留、fingerprint 冲突拒绝和 commit 单次执行。
- [ ] commit 成功或超时后进入 verify，禁止自动再次 commit。
- [ ] 只有回读状态与 preview 一致才生成成功回复。
- [ ] verify unknown/mismatch 生成接管 ticket 和安全事件。

具体工具：

- [ ] 实现五个 `prepare_*` 工具与五个 Runtime-only `commit_*` 工具。
- [ ] 实现 `create_invoice_request/report_delivery_issue/request_handoff` 的确定性低风险写入小 workflow。
- [ ] Runtime-only 工具永不出现在模型 tool schema 中。
- [ ] 退款原因原文由确定性 normalizer 生成 `reason_code`，不让模型自行改写枚举。
- [ ] 数量未提供时，只有可操作数量为 1 才默认 1，否则追问。

API 与前端：

- [ ] 实现 `POST /v1/runs/{run_id}/confirmations` 的 accept/reject、过期、重放和 409 冲突。
- [ ] 实现 `POST /v1/runs/{run_id}/cancel`、`POST /internal/v1/handoffs/{id}/resolve`。
- [ ] 实现变更 preview/确认卡，确认按钮只调 confirmation API。
- [ ] 请求进行中禁用重复点击，但安全性仍由服务端 token/幂等保证。
- [ ] 409 时重新读取 run/preview，前端不覆盖服务端状态。
- [ ] 页面不显示 confirmation token 原文，只作为请求数据保存于内存。
- [ ] 实现 `POST /v1/runs/{run_id}/confirmations/refresh`：仅在 authenticated owner 的同一 run/preview/version 仍有效时原子作废旧 token 并签发新 token，且进行限流和审计。
- [ ] `GET /v1/runs/{run_id}` 在等待确认时只返回 `token_refresh_required + preview`，不得通过 GET、SSE、trace 或日志返回旧 token 明文。
- [ ] 前端刷新后回读 run；若需要 token，则显式调用 refresh endpoint 后恢复确认卡，不把 GET 变成有副作用操作。

### 9.3 验证命令

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce
python -m pytest tests/unit/policies tests/unit/confirmation tests/unit/idempotency
python -m pytest tests/workflow/test_cancel.py tests/workflow/test_address.py tests/workflow/test_refund.py tests/workflow/test_return.py tests/workflow/test_exchange.py
python -m pytest tests/recovery/test_commit_unknown.py tests/recovery/test_confirmation_replay.py
python -m pytest tests/security/test_mutation_authorization.py tests/security/test_confirmation_binding.py
npm --prefix apps/web test -- --run
python -m pytest tests/contract/test_confirmation_refresh.py
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --track tool_workflow --judge off
```

### 9.4 验收 checklist

- [ ] 五个 mutation workflow 的正常、缺槽、政策拒绝、参数变更和 unknown 路径可回放。
- [ ] 未确认写入、跨账号写入、过期 token 写入和重复写入均为 0。
- [ ] 同一 token 并发确认两次，仅一次 commit。
- [ ] commit 请求发送后响应超时，系统查状态而不盲目重试。
- [ ] verify mismatch/unknown 时不声称成功，进入 `waiting_human`。
- [ ] 工具 trace 可串起 prepare/confirm/commit/verify，不包含 token 明文或完整地址。
- [ ] 前端反复点击确认不会产生重复 commit。
- [ ] 前端完整展示金额/渠道/影响/过期时间，用户拒绝后不再推进。
- [ ] 在 `waiting_confirmation` 刷新页面后能安全获得新 token 并继续；旧 token、跨 actor 刷新和过期 preview 均被拒绝。
- [ ] 60 个 workflow case 的 next-action/tool/args 全字段通过率 ≥ 85%，缺槽追问率 ≥ 90%。
- [ ] Phase 4 指标由最小 Harness 生成，不依赖 Phase 5 的 Judge/面板。
- [ ] Phase 4 完成后创建原子 commit，并记录 commit SHA 和 clean worktree 证据。
- [ ] Phase 4 所有 TODO 和验证命令均完成。

### 9.5 阶段产物

- `src/workflows/cancel.py`、`address.py`、`refund.py`、`return.py`、`exchange.py`
- prepare/commit/verify adapters 和 mock 业务状态
- confirmation/idempotency/handoff API
- Web preview/确认/拒绝/状态未知 UI
- mutation workflow、recovery 和 security 测试

## 10. Phase 5：EvalHarness 完整化、Judge 与评测面板

### 10.1 目标与依赖

目标：在 Phase 1/2 的 Eval Core 与最小 Harness 上增加批次持久化、Rubric Judge、三次重复运行、聚合报告和 Web 失败定位。

依赖：Phase 4 验收完成。

### 10.2 实现 TODO checklist

Harness 完整化：

- [ ] 复用 Phase 1 的 CaseLoader/hard evaluator 和 Phase 2 的 FixtureManager/RunDriver/TraceAdapter，不创建第二套评测路径。
- [ ] 实现并发上限 1、case timeout、取消、失败隔离和按 case 重跑。
- [ ] 实现 eval run/case result 持久化，同一配置可回放。
- [ ] 任意 owner、confirmation、forbidden tool、关键参数或虚假成功违规直接 hard fail。

Rubric Judge：

- [ ] 实现 Judge adapter，支持 `.env` 中独立的 `JUDGE_MODEL/JUDGE_API_BASE/JUDGE_API_KEY`；开发模式缺失时可回退 Agent 配置，但报告必须标记 `provisional/self_judged=true`。
- [ ] Release 模式强制要求显式、固定且独立于候选 Agent 的 `JUDGE_MODEL`；不满足时整体状态为 `blocked/incomplete`，不得形成 release gate。
- [ ] 仅对 150 个非纯 intent case 调用 Judge。
- [ ] 将 case/回复/证据/trace 包裹为不可信评分数据，抵抗评测注入。
- [ ] 校验 Judge JSON schema，不合法只重试一次。
- [ ] Runner 自行根据 rubric 重算 pass，不直接采信 Judge 布尔值。
- [ ] `final_pass = hard_pass AND judge_pass`；Judge 错误/缺失不默认通过。
- [ ] 保存 model/prompt/rubric/input hash、分维度分数、critical violations 和 token/延迟。
- [ ] 固定 30 条分层校准 case 与独立基准标签，记录标签来源、审核时间、rubric 版本和不可变 hash；不得由被校准的 Judge 生成自身金标。
- [ ] 输出 Judge pass/fail 一致率、逐维度偏差、边界 case 和冲突清单。

报告与前端：

- [ ] 生成 JSON 真值报告和 Markdown 摘要，不只输出单一总分。
- [ ] 实现 eval run 创建/查询/取消和 case result 分页/过滤 API。
- [ ] 实现 `/evals` 面板：进度、五 track、hard/Judge 分层指标、延迟/token。
- [ ] 实现 case 失败详情：预期/实际、hard failures、rubric 分数、脱敏 trace 引用。
- [ ] 前端不获得 API key、Judge 原始 prompt 或未脱敏 payload。
- [ ] Release 模式对每个 case 连跑 3 次，分别报告首跑成功率与三次全通过率；调试模式允许单次运行。

### 10.3 验证命令

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce
python -m pytest tests/harness/test_loader.py tests/harness/test_fixtures.py tests/harness/test_trace_adapter.py
python -m pytest tests/harness/test_hard_eval.py tests/harness/test_judge.py tests/harness/test_report.py
python -m pytest tests/security/test_judge_injection.py
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --judge off
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --judge on
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --judge on --repetitions 3 --mode release
npm --prefix apps/web test -- --run
```

### 10.4 验收 checklist

- [ ] 加载数量恰好 300，五个 track 数量分别为 150/60/50/20/20。
- [ ] 固定 case 不调用 user simulator，case 之间无状态污染。
- [ ] golden pass/fail fixtures 被 hard evaluator 100% 正确判断。
- [ ] 20 个 guardrail case 的 forbidden tool 调用次数为 0。
- [ ] Judge 不能将 hard fail 改为 pass。
- [ ] Judge 平均分门槛为 3.0/4.0，critical dimension < 2 的 case 不通过。
- [ ] 30 条校准集上 Judge pass/fail 一致率 ≥ 90%，校准报告固定 Judge/prompt/rubric 版本。
- [ ] 同一 case 连跑 3 次全部成功的比例 ≥ 80%，报告同时保留首跑指标。
- [ ] Judge 不可用时仍产生完整 hard report，整体状态明确标记 incomplete。
- [ ] Release report 的 `self_judged=false` 且 Judge 配置完整；开发回退报告不能被标为 release pass。
- [ ] `/evals` 能定位到单个失败 case，hard fail 和 Judge fail 可分开过滤。
- [ ] 报告固定 dataset/model/prompt/workflow/policy/tool/rubric 版本和 hash。
- [ ] 300-case 各轨指标达到上位设计第 11.2 节门槛。
- [ ] Phase 5 完成后创建原子 commit，并记录 commit SHA 和 clean worktree 证据。
- [ ] Phase 5 所有 TODO 和验证命令均完成。

### 10.5 阶段产物

- `src/harness/loader.py`、`fixtures.py`、`runner.py`、`trace_adapter.py`
- `src/harness/hard_eval.py`、`judge.py`、`report.py`
- `evals/commerce_bench_zh/calibration_labels.jsonl`、校准报告与标签 provenance/hash
- eval API 和 `apps/web` 评测面板
- `evals/reports/<eval_run_id>/report.json`、`report.md`
- Harness/Judge/注入/前端测试

## 11. Phase 6：安全、恢复与运维硬化

### 11.1 目标与依赖

目标：在不增加新业务能力的前提下，系统性验证越权、注入、PII、并发、崩溃、上游失败、备份和资源边界。

依赖：Phase 5 验收完成。

### 11.2 实现 TODO checklist

安全：

- [ ] 实现用户输入、RAG 文档和 ToolResult 的不可信数据标记。
- [ ] 实现 Decision 工具白名单和系统字段拒绝，注入内容不能扩权。
- [ ] 实现 tenant + actor + owner 多层校验和统一不泄露错误。
- [ ] 实现输入/存储/模型/trace/输出五个边界的 PII 脱敏。
- [ ] 实现 `security_audit_events` append-only 写入和独立查询权限。
- [ ] 禁止前端 source map/环境注入泄露 API key、DB URL 和内部 ID。
- [ ] 实现仓库、镜像、前端 bundle、日志和报告的 secret scan；只报告变量名/文件位置，不输出匹配到的 secret 值。
- [ ] `DEMO_MODE=false` 时完全禁用 demo actor/scenario API。

恢复与降级：

- [ ] 在模型请求、工具前/后、checkpoint 前/后、commit 前/后注入崩溃。
- [ ] 实现模型、RAG、只读工具、写工具、DB、TraceStore 和 Judge 的明确降级。
- [ ] 实现 waiting/confirmation 过期任务和 outbox dead-letter 处理。
- [ ] 实现优雅关闭：停止接收新 run，完成/中断当前安全 step，保存 checkpoint。
- [ ] 实现 PostgreSQL 备份/恢复脚本和恢复演练文档。
- [ ] 实现 `scripts/soak_monitor.sh`：非交互后台运行、记录 PID/开始结束时间、定期采集容器资源和错误计数、支持 status/stop，并原子写结果。

可观测与资源：

- [ ] 输出结构化 JSON 日志，字段包含 request/run/step/tool/error/version，不含原始密钥/PII。
- [ ] 实现延迟、超时、工具错误、Judge 错误、安全事件、当前 run/eval 队列指标。
- [ ] 评测执行时持续检查内存/磁盘；实际可用盘 < 3 GiB 时停止新批次。
- [ ] 限制 Uvicorn 1 worker、DB pool 5+2、Eval 并发 1；当前主机不启动额外 worker 容器。
- [ ] 实现 trace/report 保留和清理策略，不使用未校验的宽范围递归删除。
- [ ] 实现 live/ready 与运行异常的安全错误信封。

### 11.3 验证命令

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce
python -m pytest tests/security
python -m pytest tests/recovery
python -m pytest tests/contract/test_error_envelopes.py tests/contract/test_redaction.py
python -m pytest tests/deployment/test_backup_restore.py tests/deployment/test_graceful_shutdown.py
docker compose up -d --build
docker compose ps
docker stats --no-stream
scripts/soak_monitor.sh --duration 10m --interval 30s --output evals/reports/soak-smoke.json --detach
scripts/soak_monitor.sh --status --output evals/reports/soak-smoke.json
```

### 11.4 验收 checklist

- [ ] prompt/tool/RAG/Judge 注入无法扩大工具白名单、scope 或状态机权限。
- [ ] 跨 actor/租户的读写均被拒绝，返回不泄露资源存在性。
- [ ] 密钥、confirmation token、完整手机/地址/支付信息不出现在日志、trace、报告或前端 bundle。
- [ ] 崩溃注入后的 run 可恢复或安全失败，不重复副作用。
- [ ] 任意写工具状态 unknown 时不对用户声称成功。
- [ ] DB 备份可恢复到空实例，conversation/run/checkpoint/event 关系完整。
- [ ] app + DB 稳态使用不突破容器上限，不依赖 swap 才能处理单会话。
- [ ] 模型/Judge 不可用时的降级回复不产生 mutation。
- [ ] P0 安全和恢复断言全部通过。
- [ ] soak monitor 的短时自测可启动、查询、停止并生成无密钥的完整 JSON；24 小时 gate 留在 Phase 7。
- [ ] Phase 6 完成后创建原子 commit，并记录 commit SHA 和 clean worktree 证据。
- [ ] Phase 6 所有 TODO 和验证命令均完成。

### 11.5 阶段产物

- `src/guardrails/`、`src/telemetry/`、安全审计 API
- 过期/outbox/降级/优雅关闭任务
- `scripts/backup_db.sh`、`scripts/restore_db.sh`
- `scripts/soak_monitor.sh`
- `docs/runbooks/failure-recovery.md`、`backup-restore.md`、`security.md`
- security/recovery/deployment 测试报告

## 12. Phase 7：全链路候选版本与交付验收

### 12.1 目标与依赖

目标：不再增加功能，生成可复现的 internal beta 候选版本和完整证据包。

依赖：Phase 0～6 验收完成。

### 12.2 实现 TODO checklist

- [ ] 冻结代码、依赖、DB migration、prompt、workflow、policy、tool schema、dataset 和 rubric 版本。
- [ ] 确认 Git worktree clean，记录 `git rev-parse HEAD`；报告中的 `source_commit` 必须对应实际执行代码，禁止仅写分支名。
- [ ] 从空数据库执行全新部署，不依赖开发机残留状态。
- [ ] 执行后端、前端、workflow、security、recovery 和 deployment 全量测试。
- [ ] 使用独立 Judge 对固定 300-case 执行三次 release run；Judge 缺失、同候选模型或任一 case 无结果时不得通过。
- [ ] 生成按 track 分层的正式 JSON/Markdown 报告。
- [ ] 从 Web 完整演示 FAQ/商品对比、订单物流、退款确认和失败 case 定位。
- [ ] 执行 Compose 停止/重启，验证会话、run、checkpoint、评测报告不丢失。
- [ ] 执行备份/恢复演练，记录恢复点和验证查询。
- [ ] 使用 `scripts/soak_monitor.sh` 非交互记录连续 24 小时运行中的内存、磁盘、错误率和外部 API 失败；通过 status/产物回读，不用阻塞式 `sleep` 占用会话。
- [ ] 完成 `README.md`、本地启动、评测、数据库、故障恢复和已知限制文档。
- [ ] 明确标记当前产物为 `internal beta / mock business data`，不声称可执行生产退款。
- [ ] 提交最终脱敏证据和文档，记录证据 commit SHA；候选源码 commit 与证据 commit 分开记录，必要时创建 annotated internal-beta tag。
- [ ] 将可提交的脱敏发布摘要写入 `docs/releases/<release_id>/`；`evals/reports/` 中的原始运行产物保持忽略，不使用 `git add -f` 提交。

### 12.3 验证命令

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commerce
test "$CONDA_DEFAULT_ENV" = commerce
test -z "$(git status --porcelain)"
git rev-parse HEAD
python -m pytest
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
docker compose config --quiet
docker compose up -d --build
curl -fsS http://127.0.0.1:18437/health/live
curl -fsS http://127.0.0.1:18437/health/ready
python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --judge on --repetitions 3 --mode release
scripts/soak_monitor.sh --duration 24h --interval 60s --output evals/reports/release-soak.json --detach
scripts/soak_monitor.sh --status --output evals/reports/release-soak.json
```

24 小时 soak 启动命令应立即返回；只有后续 `--status` 显示 `completed`、采样窗口达到 24 小时且产物校验通过后，才能勾选对应验收项。

### 12.4 最终验收 checklist

功能：

- [ ] FAQ/政策、商品检索/对比、订单/物流、五个事务 workflow 和人工接管均可执行。
- [ ] Web 对话页、run Trace 页和评测面板均可展示并可刷新恢复。

安全：

- [ ] 跨账号/跨租户工具调用为 0。
- [ ] 未确认、重放、参数篡改和重复 commit 为 0。
- [ ] 密钥、完整 PII、token 明文和隐藏思维链不出现在可见产物中。
- [ ] 任意安全 hard fail 都不能被 Judge 高分抵消。

评测：

- [ ] 300 条 case 全部产生结果或明确的非默认通过错误。
- [ ] intent/route ≥ 90%，workflow 全字段 ≥ 85%，RAG 事实覆盖 ≥ 90%，evidence 精度 ≥ 95%。
- [ ] clarification required slot 命中 ≥ 85%，forbidden tool = 0。
- [ ] Judge 平均分 ≥ 3.0/4.0，critical dimension 低于 2 的 case 不通过。
- [ ] 三次全通过比例 ≥ 80%，Judge 校准一致率 ≥ 90%，且 release report 为 `self_judged=false`、`status=complete`。

工程：

- [ ] `docker compose up -d --build` 一条命令可启动。
- [ ] app + DB 上限 640 MiB，默认无额外 worker/Redis/本地模型。
- [ ] DB 重启、应用重启和备份恢复后核心数据完整。
- [ ] 所有报告可追溯到代码、模型、prompt、workflow、policy、tool、dataset 和 rubric 版本。
- [ ] 正式报告中的 `source_commit` 等于 clean worktree 的候选 commit SHA，24 小时 soak 产物完整。
- [ ] 所有 Phase 0～7 验收 checklist 已勾选。

### 12.5 交付产物

- 自研 Agent Runtime、workflow、ToolRegistry、PolicyEngine 和 EvalHarness 源码
- PostgreSQL migrations、Dockerfile、Compose 和备份/恢复脚本
- React 对话工作台、run Trace 和评测面板
- 300-case 正式评测报告和脱敏失败详情
- 启动、评测、安全、故障恢复、备份和已知限制文档
- `docs/releases/<release_id>/` 脱敏发布摘要、候选源码 SHA、证据 SHA 和 internal-beta tag（如创建）

## 13. 全局测试矩阵

| 测试层 | 必测内容 | 最低执行频率 |
|---|---|---|
| Unit | reducer、validator、policy、token、idempotency、RAG ranker、UI components | 每个相关变更 |
| Schema/Contract | model/tool/API/repository/migration/fixture/schema compatibility | 每个相关变更 |
| Workflow | readonly、refund、cancel、address、return、exchange、handoff | 每次合并前 |
| Recovery | checkpoint 前后崩溃、并发 advance、重放、unknown commit | 每次合并前 |
| Security | owner/tenant、PII、prompt injection、tool injection、Judge injection | 每次合并前 |
| Frontend | API contract、SSE 续传、刷新恢复、确认防重、响应式 | 每次合并前 |
| Harness | fixture 隔离、hard eval、Judge error、report reproducibility | 每次合并前 |
| Regression | 300 个静态 case | 候选版本必跑 |
| Deployment | Compose、migration、ready、resource limits、restart、backup/restore | 候选版本必跑 |

建议 CI 顺序：

```text
format/lint
  → unit
  → schema/contract
  → workflow
  → recovery/security
  → frontend build/test
  → 300-case hard evaluation
  → Judge batch（普通变更可选，release 必跑且必须独立）
  → report artifacts
```

## 14. Codex 执行记录

每完成一个垂直切片或阶段，在下方追加记录。不要覆盖历史记录。

```markdown
### YYYY-MM-DD — Phase N — <切片名>

- 状态：completed | partial | blocked
- 变更文件：
  - `path/to/file`
- 执行验证：
  - `<command>` → pass/fail
- 关键证据：
  - `<result or artifact path>`
- 剩余 TODO：
  - `<unchecked item>`
- BLOCKED：无 | <具体阻塞与所需输入>
```

### 2026-09-13 — Phase 0 — 工程骨架与本地质量门禁

- 状态：completed
- 变更文件：
  - `pyproject.toml`、`src/`、`apps/`、`tests/`
  - `infra/migrations/`、`infra/postgres/init/00-create-roles.sh`
  - `Dockerfile`、`compose.yaml`、`.dockerignore`、`.env.example`
  - `scripts/check_secrets.py`、`scripts/deployment_smoke.sh`
  - `docs/runbooks/local-development.md`
- 执行验证：
  - `python -m ruff check src apps tests scripts/check_secrets.py` → pass
  - `python -m mypy src apps` → pass
  - `python -m pytest tests/unit` → pass（3 passed）
  - `npm --prefix apps/web run lint && npm --prefix apps/web run typecheck && npm --prefix apps/web test -- --run && npm --prefix apps/web run build` → pass
  - `python scripts/check_secrets.py --repository . --tracked-only`、`--git-history --redact` → pass
- 关键证据：
  - 已构建的 `apps/web/dist/` 由 FastAPI 单测验证可同源服务并覆盖三个 SPA 路由。
  - 工程骨架源码提交：`cb1b193`（提交后工作区为 clean）。
- 执行验证（补充）：
  - `docker compose build`、真实 `.env` 的 DB bootstrap 与 `python -m src.migrate` → pass
  - `scripts/deployment_smoke.sh` → pass（创建、app/DB 重启、记录保留）
  - runtime DDL、扩展创建及跨 schema 查询 → 均被拒绝
  - `.env` policy、Git history、镜像/前端产物/容器日志扫描 → pass
- 剩余 TODO：无。
- BLOCKED：无。

### 2026-09-13 — Phase 1 — 协议、迁移与 Eval Core 首批切片

- 状态：in_progress
- 变更文件：
  - `src/protocols.py`、`tests/unit/test_protocols.py`
  - `src/harness/schema.py`、`src/harness/loader.py`、`src/harness/hard_eval.py`
  - `src/mutation_safety.py`
  - `infra/migrations/versions/20260913_0002_runtime_core.py`
  - `infra/migrations/versions/20260913_0003_mutation_safety.py`
  - `tests/harness/`、`tests/unit/test_mutation_safety.py`
- 执行验证：
  - Phase 1 协议、loader、hard evaluator、mutation safety 单测 → pass（当前累计 12 项相关测试）
  - `python -m mypy src`、`python -m ruff check` → pass
  - 真实 PostgreSQL 空库前向迁移至 `20260913_0004`，七个 schema 共 19 张表已核验
  - `scripts/run_phase1_contract_tests.sh` → pass（独立 Compose DB；migration/schema 2 项、RunRepository 原子性/回滚/并发/租户隔离 5 项）
  - `python -m pytest tests/unit/test_health.py tests/unit/test_protocols.py tests/unit/test_mutation_safety.py tests/harness/test_loader.py tests/harness/test_hard_eval.py` → pass（12 passed）
- 关键证据：
  - 提交：`32595e0`、`893203c`、`6a7329d`、`bad9f67`、`49c05fc`、`39f99aa`、`16dcdf7`、`f5a83b0`
  - `cases.jsonl` 已验证 300 条，五轨计数为 `150/60/50/20/20`，dataset hash 可复现。
- 剩余 TODO：
  - 实现 Confirmation/Evaluation/Memory/Knowledge/Audit repository、confirmation/idempotency 原子消费与 outbox lease。
  - 完成 300-case 语义审核清单和 `quality-audit.md`。
  - 完成 Phase 1 全部验证命令后再标记阶段完成。
- BLOCKED：无。

### 2026-09-13 — Phase 1 — 阶段验收

- 状态：completed
- 验证：`test_protocols.py` 3 passed；独立 Compose PostgreSQL contract suite 16 passed；Eval Core/数据合同 7 passed；`ruff` 与 `mypy src` → pass。
- 关键保证：空库前向迁移至 `20260913_0005`；run checkpoint 原子性/并发/租户隔离、confirmation/idempotency、outbox lease、版本不可变 trigger 均有 PostgreSQL 合同覆盖。
- 阶段提交：`d3b3b13`。
- 工作区：阶段提交后仅保留用户预存的 `AGENTS.md` 未提交修改；本阶段文件均已提交。

### 2026-09-14 — Phase 2 — 自研 Runtime 与最小 Harness v2.2 单步基线验收

- 状态：completed
- 变更文件：
  - `src/models/gateway.py`、`src/agent/loop.py`、`src/orchestration/`
  - `src/tools/registry.py`、`src/tools/executor.py`、`src/policies/engine.py`
  - `src/harness/runtime.py`、`src/harness/deterministic_runtime.py`、`src/harness/run_driver.py`、`src/harness/runner.py`
  - `src/repositories/model_invocations.py`、`evals/commerce_bench_zh/cases.runtime.jsonl`
  - 对应 unit、workflow、harness、PostgreSQL contract/recovery 与 live smoke 测试。
- 执行验证：
  - `python -m ruff check src apps tests`、`python -m mypy src apps` → pass。
  - `python -m pytest -q tests` → `110 passed, 29 skipped`；跳过项仅为未注入隔离 PostgreSQL URL 或未显式启用 live 的 opt-in 测试。
  - `scripts/run_phase1_contract_tests.sh tests/recovery/test_postgres_checkpoint_recovery.py tests/recovery/test_postgres_event_replay.py tests/recovery/test_postgres_mutation_recovery.py` → 隔离 PostgreSQL `28 passed`。
  - `python -m src.harness.runner --dataset evals/commerce_bench_zh/cases.jsonl --track intent_route --judge off` → `150/150` hard-pass；五个 track 均有独立 case-id Runtime 驱动与 hard-eval 测试。
  - `RUN_LIVE_MODEL_TEST=1 python -m pytest -q -m live tests/integration/test_model_gateway_live.py` → `1 passed in 3.45s`；只记录脱敏的模型标识、配置指纹与延迟字段。
  - `python scripts/check_secrets.py --repository . --tracked-only --env-policy .env --frontend apps/web --git-history` → pass。
- 关键证据：
  - 固定八阶段 pipeline、运行创建版本锁定、事件回放与 mutation 崩溃恢复：`6e829fc`、`f9c72d3`、`2b93e4f`、`3ded8ae`。
  - 150 条 intent_route Runtime fixture、完整 CLI hard-eval：`303ea9b`。
  - owner/resource binding、workflow/step/scope 解析、同步 adapter deadline、模型与 prompt 指纹审计：`795e5c4`。
  - API readiness 的无网络 registry 检查：`8035717`。
  - 五轨代表性 Runtime 执行：`f1b1813`。
- 剩余 TODO：当时无；2026-09-14 用户确认采用双执行器后，本记录只证明 `run_step()` 单步基线，不再证明 Phase 2 v2.5 的有界 `while` 主循环和主模型意图分类器已经完成。
- BLOCKED：无。

### 2026-09-14 — Phase 2 — 双执行器与有界 while 设计增量

- 状态：in_progress
- 设计决定：只读任务使用 `AgentLoop.run()` 有界 while；每轮经 StepPipeline 调用 AgentStepExecutor 并先原子 checkpoint，再决定继续。写任务使用确定性 WorkflowExecutor，禁止进入模型自由循环。意图分类器使用独立 `CLASSIFIER_*` 配置名，但模型、端点和 Key 与主 Agent 相同且温度固定 0.1；代码完成最终风险复核和执行器选择。
- 文档变更：
  - `docs/plan/feasibility-and-implementation-plan.md`
  - `docs/plan/phased-implementation-execution-plan.md`
- 已有可复用基础：八阶段单步管线、运行版本锁定、ToolExecutor 安全边界、checkpoint/recovery、最小 Harness。
- 剩余 TODO：实现本阶段新增的主模型意图分类 profile、`AgentLoop.run()`、执行器选择、WorkflowExecutor 入口、多轮 fixture/trace 以及新增恢复与安全测试。
- BLOCKED：无。

### 2026-09-14 — Phase 2 — 双执行器首批实现切片

- 状态：partial
- 已完成：
  - Classifier 显式配置、与主 Agent 模型/端点/Key 的安全一致性校验，以及 `CLASSIFIER_TEMPERATURE=0.1` 的 readiness fail-closed。
  - `IntentClassification`、fake classifier 和代码拥有最终裁决权的 `IntentRouter/RouteDecision`。
  - `AgentStepExecutor.execute_step()` 单轮原语、兼容 `run_step()` 入口，以及基于每轮新 checkpoint context 的有界 `AgentLoop.run()`。
  - 只读 loop 写工具防火墙、重复等价只读动作安全 handoff、确定性 `WorkflowExecutor` 最小入口。
  - Harness 在存在 Pipeline 的计划下直接驱动多轮 `AgentLoop.run()`，并聚合完整工具 trace。
  - 双执行器数据库 migration `20260914_0006`：允许路由前状态为空、选定后不可变，并约束 mode/status 组合。
- 关键提交：`c4d4102`、`dc85345`、`2239fe4`、`ca541fa`、`f8d1852`、`4536ae7`、`f2ca959`、`1cea071`、`74bf37b`。
- 执行验证：
  - `python -m pytest tests/unit tests/workflow tests/harness` → `131 passed`。
  - `python -m mypy src apps` → pass；`python -m ruff check src apps tests` → pass。
  - migration 单元检查 → `2 passed`；PostgreSQL contract tests 因未设置 `DATABASE_TEST_URL` 跳过。
- 剩余 TODO：完成真实 PostgreSQL dual-executor contract、跨轮 cancellation/token/no-progress 恢复、执行器选择接入 OrchestrationEngine/API、fixture 的通用多轮 schema，以及 Phase 2 全部验证/验收项。
- BLOCKED：无。

## 15. 停止或请求用户输入的条件

Codex 应在以下情况停止扩张实现，完成仍可安全完成的检查后，向用户说明所需决策：

- 需要将 Demo 从 `127.0.0.1` 暴露到公网；
- 需要调用真实订单/退款 API 并产生真实副作用；
- 需要新的密钥、租户凭据、业务政策或真实数据授权；
- Release 缺少独立 Judge 配置或缺少独立的 30 条校准基准标签；此时可以继续开发/hard eval，但 release 状态只能是 `blocked/incomplete`；
- 需要删除未明确属于本项目的数据、Docker volume 或其他服务容器；
- 技术设计与当前用户指令冲突，且不同选择会显著改变结果；
- 完成原型后要将 `internal beta` 提升为生产自动执行系统。

外部模型/Judge 临时不可用不会阻止所有开发：应继续使用 fake model 完成 Runtime、workflow、硬判分和前端，并只将需要真实模型的验收项保持为 `[ ]`。
