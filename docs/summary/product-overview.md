# CommerceAgent 产品说明

## 1. 产品定位

CommerceAgent 是一个面向电商客服场景的 Agent 演示工作台，重点不是只生成一句聊天回复，而是把 Agent 从接收用户请求到完成业务动作的全过程变成可观察、可校验、可恢复的执行链。

产品当前聚焦四个能力环节：

1. 把业务诉求翻译成结构化 AI 任务；
2. 用代码约束的方案和架构执行任务；
3. 沉淀对话、执行、审核和评测数据，为后续数据闭环提供基础；
4. 通过确定性评测与独立 Judge 验证能力。

当前版本是 internal beta，业务订单、商品、物流和售后接口仍以 mock adapter 为主，不代表生产业务系统能力。

## 2. 把业务诉求翻译成 AI 任务

### 2.1 业务目标

电商客服用户通常提出的是自然语言诉求，例如：

- 查询订单状态或物流预计送达时间；
- 查询商品规格、功能或多个商品的差异；
- 申请退款、退货、换货、取消订单或修改订单；
- 询问配送、退款、支付和售后政策；
- 在信息不足、存在越权风险或自动处理不安全时转人工。

系统将这些诉求拆解为可验证的结构化任务，而不是直接让模型自由决定业务动作。

### 2.2 任务结构

用户请求会经过以下转换：

```text
自然语言消息
    ↓
意图识别 + 风险识别
    ↓
代码维护的 intent → execution mode → route
    ↓
槽位提取与缺失信息判断
    ↓
结构化 Decision
    ↓
只读查询 / 确定性业务 Workflow / 澄清 / 人工接管
```

核心结构化字段包括：

| 字段 | 作用 |
|---|---|
| `intent` | 用户要完成的业务意图，例如 `track_order`、`request_refund` |
| `route` | 代码锁定的业务路由，例如 `order_query`、`refund`、`product_query` |
| `execution_mode` | `readonly_loop` 或 `workflow` |
| `next_action` | `call_tool`、`respond`、`ask_user`、`handoff` 等下一步动作 |
| `tool` / `args` | 需要调用的工具及业务参数 |
| `required_slots` | 完成任务所需的订单号、商品号、原因等信息 |
| `evidence_ids` | RAG 回答可以引用的可信证据标识 |

意图、路由和槽位定义见[路由目录](../../src/orchestration/route_catalog.py)、[意图分类器](../../src/agent/intent_classifier.py)和[槽位提取器](../../src/agent/slot_extractor.py)。

### 2.3 只读任务与有副作用任务

系统将业务任务分成两条路线：

| 路线 | 适用业务 | 处理方式 |
|---|---|---|
| Read-only loop | 订单查询、商品查询、物流查询、政策查询 | 有界 Agent Loop，工具白名单，最多限定步数，不能产生写副作用 |
| Deterministic workflow | 退款、退货、换货、取消、改地址等 | 代码编排，按照准备、确认、提交、核验执行 |

写操作必须经过 `preview → user confirmation → commit → verify`。模型只能提出结构化候选，不能绕过代码路由、权限检查或确认边界直接提交。

## 3. 方案与架构

### 3.1 一次请求的执行链

```text
用户消息
  ↓
Web Workbench / FastAPI
  ↓
原子创建 Conversation + Run
  ↓
Intent Classifier：意图与风险识别
  ↓
Router：代码锁定 route、workflow 和 tool allowlist
  ↓
AgentLoop 或 WorkflowExecutor
  ↓
DecisionValidator + Policy + Tenant/Owner Check
  ↓
ToolExecutor
  ├── Mock 订单、商品、物流和售后工具
  └── PostgreSQL 知识库检索工具
  ↓
可信 ToolResult / Evidence
  ↓
Checkpoint + Event + Outbox
  ↓
最终回复 / 等待用户 / 等待人工 / 可重试失败
```

系统通过 [AgentLoop](../../src/agent/loop.py)、[StepPipeline](../../src/orchestration/pipeline.py)和[运行时组合](../../src/orchestration/api_runtime.py)组织执行；状态、checkpoint、事件和终态回复持久化到 PostgreSQL。

### 3.2 关键架构原则

- **模型负责理解和表达，代码负责边界和动作**：模型不能自行扩大路由或工具权限。
- **Fail closed**：决策校验、权限、资源归属或政策检查失败时不触达写操作边界。
- **可信观察分层**：工具结果经过归一化和持久化后，才可以作为下一轮模型输入。
- **可恢复**：每个关键步骤保存 checkpoint 和事件，进程重启或 SSE 断线后可以恢复 Run。
- **幂等**：用户消息、确认 token、写操作和终态回复均有幂等或版本控制。
- **数据最小化**：Trace、模型调用和审计记录脱敏，不保存 API Key、隐藏思维链和不必要的个人信息。

### 3.3 RAG 检索流程

项目包含 RAG 流程，但当前是轻量级 PostgreSQL 检索，不是 embedding 向量检索系统。

```text
evals/commerce_bench_zh/knowledge.jsonl
  ↓ scripts/ingest_demo_knowledge.py
knowledge_documents + knowledge_chunks
  ↓ retrieve_knowledge
租户 / 权限 / 生效时间 / active 状态过滤
  ↓
PostgreSQL similarity 排序
  ↓
应用层关键词与中文 2/3-gram 重排
  ↓
EvidencePack：evidence_id、片段、来源、版本、分数
  ↓
Agent 只能引用已返回的 evidence_id
```

相关实现：

- [知识导入](../../src/rag/ingestion.py)；
- [检索与 CJK n-gram 排序](../../src/rag/retrieval.py)；
- [PostgreSQL 知识 Repository](../../src/repositories/knowledge.py)；
- [`retrieve_knowledge` 工具适配器](../../src/tools/adapters/knowledge.py)。

RAG 回答中的证据 ID 会进入可信边界，并在下一轮 Prompt 中提供给 Agent。若没有足够证据，系统应拒绝补充未经证实的事实。

### 3.4 数据与信任边界

```text
用户输入 / 模型候选 / RAG 文本 / ToolResult
                 │ 不可信
                 ▼
DecisionValidator + Policy + Owner Check
                 │ 通过后
                 ▼
ToolExecutor / Workflow
                 │
                 ├── 可信观察
                 ├── Checkpoint / Event / Audit
                 └── 用户可见终态回复
```

更多表结构、状态机、工具合同和安全边界见[总体技术设计](../plan/feasibility-and-implementation-plan.md)。

## 4. 失败归因、自进化与发布控制面

当前代码已具备受控的持续改进骨架：失败 Run、人工接管、用户点踩和评测失败可以沉淀为脱敏失败样本；确定性 taxonomy 先做归因，自动分析结果只能作为待复核证据。达到至少 5 个不同来源且通过安全/离线门禁后，才可生成 tenant 级 Skill 候选。

Skill 的关键状态为：

```text
CANDIDATE → PENDING_REVIEW → APPROVED → CANARY → ACTIVE
                         └→ REJECTED / EXPIRED / ROLLED_BACK
```

自动评测没有真人审批时，候选必须停在 `PENDING_REVIEW`，不能自动批准、Canary 或全量上线。生产控制面由 `INTERNAL_ADMIN_TOKEN` 保护，后续可将同一 API 边界替换为 OIDC/RBAC。

前端控制面可查看失败样本、归因证据、Skill 状态漏斗、发布阶段和自动停止原因；对话 Run 页面则可视化 Safety Router、意图识别、策略路由、RAG、工具、Guardrail、回复发布以及 Token/成本/时延，但不会展示隐藏 Prompt 或思维链。当前 Shadow/Canary 实际分流和调度仍属于后续阶段，空页面显示“暂无真实记录”。

## 4. 数据飞轮

### 4.1 当前状态：有数据沉淀，没有完整飞轮

项目已经具备数据采集和分析基础：

| 已有数据 | 用途 |
|---|---|
| Conversation、Message | 保存用户请求和客服回复的脱敏记录 |
| Run、Checkpoint、Event | 回放 Agent 状态、步骤和异常 |
| Model Invocation | 记录模型调用目的、版本、延迟和脱敏摘要 |
| Tool Invocation | 记录工具、参数摘要、结果和错误 |
| Handoff Ticket | 保存人工接管原因、待处理动作和审核结果 |
| Knowledge Document/Chunk | 保存版本化知识文档和可引用片段 |
| Evaluation Result | 保存 hard evaluator、Judge、rubric 和发布结果 |
| Audit Event | 保存越权、注入、确认绕过等安全事件 |

这些数据为后续的数据迭代提供了基础，但当前还不能称为完整的数据飞轮。

### 4.2 当前缺少的闭环

```text
线上业务数据
  ↓
用户反馈 / 人工修正
  ↓
样本清洗、标注、审核
  ↓
Prompt / RAG / 评测集迭代
  ↓
重新评测、灰度和发布
```

当前尚未实现：

- 用户满意度、点赞/点踩、纠错等反馈入口；
- 将人工审核自动转成训练/评测标注的流程；
- 自动从失败 Trace 生成新 case 并进入审核队列；
- 反馈驱动的知识库更新和版本比较；
- 从线上数据到 Prompt、RAG 或模型版本的自动实验流水线。

因此，当前产品的真实定位是“可审计数据基础 + 离线评测”，而不是已经完成数据闭环的学习型客服产品。

### 4.3 后续可扩展方向

后续可以在不改变现有 Trace 和评测合同的前提下增加：

1. Run 级用户反馈和人工修正标签；
2. 脱敏样本池与人工标注审核队列；
3. 失败 case 自动聚类、回归集增量和数据版本哈希；
4. Prompt、知识版本和模型配置的离线 A/B 实验；
5. 通过评测 gate 后再进行灰度发布，并把线上反馈回流到下一轮实验。

## 5. 评测体系与实验

### 5.1 评测集

项目使用 `commerce-bench-zh` 静态中文电商客服评测集，共 300 个 case：

| Track | 数量 | 核心验证内容 |
|---|---:|---|
| `intent_route` | 150 | 意图和路由精确匹配 |
| `tool_workflow` | 60 | 槽位、工具、参数、确认和资源归属 |
| `rag_grounding` | 50 | 商品事实、回答覆盖和证据引用 |
| `scripted_clarification` | 20 | 是否追问正确的缺失属性 |
| `guardrail_handoff` | 20 | 越权、注入、隐私、未确认写入和人工接管 |

数据字段、来源和适用边界见[评测集说明](../../evals/commerce_bench_zh/README.md)、[数据来源](../../evals/commerce_bench_zh/SOURCES.md)和[数据许可](../../evals/commerce_bench_zh/LICENSE-DATA.md)。

### 5.2 双层判分

第一层是确定性 hard evaluator，直接检查结构化 trace 和业务约束：

- `intent`、`route`、`next_action`、`tool`、`args`；
- required slots、evidence IDs 和资源 owner；
- 工具调用顺序、确认状态和最终工具状态；
- forbidden tool、越权、未确认写入和虚假成功。

第二层是独立 Rubric Judge，只评价需要自然语言判断的 case。Judge 使用 0～4 分量表，按 Track 评价不同维度：

- workflow：任务推进、确认清晰度、无虚假成功、表达清晰度；
- RAG：事实正确、证据支撑、问题覆盖、表达清晰度；
- clarification：属性追问、上下文相关性、可回答性、自然度；
- guardrail：安全政策、无虚假成功、安全下一步、专业语气。

最终结果为：

```text
case_pass = hard_pass AND judge_pass
```

安全或关键业务 hard fail 不能被语言质量分数抵消。Judge 的 rubric 和 Prompt 见 [rubrics.json](../../evals/commerce_bench_zh/rubrics.json) 与 [JUDGE_PROMPT.md](../../evals/commerce_bench_zh/JUDGE_PROMPT.md)。

### 5.3 实验与发布规则

- 每个 case 最多重复运行 3 次，报告首轮通过率和三次全通过率；
- 固定 dataset hash、runtime fixture hash、Prompt hash、rubric 版本和 Judge Prompt hash；
- 使用 30 个人工标注 case 做 Judge 校准；
- Release 模式要求独立 Judge，禁止候选 Agent 自评；
- 报告同时输出 Track 通过数、hard/judge/final 结果、每个 rubric 指标平均分和加权总分平均分；
- 失败 case 需要结合 Trace、hard fail 原因和 Judge 维度分数分析，不能只看一个总分。

### 5.4 当前结果与解释

最新 Internal Beta 结果见[发布摘要](../releases/internal-beta-20260916-r4/release-summary.md)和本地[详细 Markdown 报告](../../evals/reports/release-20260916-bounded-judge-v2/report.md)：

- 300 case × 3 次，共 900 次运行；
- hard pass：`300/300`；
- 最终通过：`296/300`；
- 三次全通过率：`98.67%`；
- Judge 校准一致率：`100%`。

这个结果是固定静态评测集上的回归结果，不应解释为生产环境成功率。当前评测使用 deterministic fixture，主要验证 AgentLoop、工具合同、安全边界、RAG grounding 和报告链路；真实业务上线前还需要接入真实模型、业务 API、脱敏线上 case 和未见数据。

### 5.5 评测报告中的代表性指标

当前详细报告会按整体和 Track 输出 Judge 指标平均分。整体均分示例：

| 指标 | 平均分（0～4） |
|---|---:|
| `factual_correctness` | 3.9200 |
| `evidence_grounding` | 3.9200 |
| `question_coverage` | 3.9600 |
| `task_progress` | 3.9944 |
| `safe_next_step` | 2.0000 |
| `professional_tone` | 3.0000 |
| Judge 加权总分 | 3.8693 |

这些指标用于发现具体短板。例如 `safe_next_step` 和 `professional_tone` 的分数明显低于事实正确性，说明安全场景下“拒绝之后如何继续帮助用户”仍有改进空间。

## 6. 当前产品边界

当前版本适合：

- 展示电商客服 Agent 的可观察执行过程；
- 验证意图路由、工具协议、RAG 引用、澄清和安全边界；
- 进行固定数据集上的离线回归和发布证据管理；
- 作为接入真实订单系统前的工程原型。

当前版本不应被描述为：

- 已接入真实订单、支付、退款和物流主系统；
- 已完成线上用户反馈驱动的数据飞轮；
- 已证明真实生产环境有 `98.67%` 的任务成功率；
- 已具备模型训练、后训练或自动学习能力。

## 7. 相关文档

- [项目 README](../../README.md)
- [总体技术设计](../plan/feasibility-and-implementation-plan.md)
- [本地开发手册](../runbooks/local-development.md)
- [故障恢复手册](../runbooks/failure-recovery.md)
- [数据库备份与恢复](../runbooks/backup-restore.md)
- [评测数据集说明](../../evals/commerce_bench_zh/README.md)
- [最新发布摘要](../releases/internal-beta-20260916-r4/release-summary.md)
