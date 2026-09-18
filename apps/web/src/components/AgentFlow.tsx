import styles from "../styles/App.module.css";

type RunSnapshot = {
  run_id?: string;
  status: string;
  current_step: string;
  step_count: number;
  execution_mode?: string;
};

type FlowEvent = {
  id?: number;
  type: string;
  step_id?: string;
  payload?: Record<string, unknown>;
};

type AgentFlowProps = {
  run: RunSnapshot | null;
  events: FlowEvent[];
  evidenceCount: number;
};

type FlowState = "pending" | "active" | "done" | "warning" | "failed" | "na";
type StageId = "intake" | "safety" | "domain" | "intent" | "policy" | "executor" | "guard" | "response";

const TERMINAL_STATUSES = new Set(["completed", "cancelled", "expired"]);
const WAITING_STATUSES = new Set(["waiting_user", "waiting_confirmation", "waiting_human"]);

const statusLabels: Record<string, string> = {
  created: "已创建", routing: "路由中", running_readonly: "只读执行中", running_workflow: "流程执行中",
  waiting_user: "等待补充", waiting_confirmation: "等待确认", waiting_human: "等待人工",
  committing: "提交中", verifying: "校验中", completed: "已完成", failed: "失败", cancelled: "已取消", expired: "已过期",
};

const valueLabels: Record<string, string> = {
  low: "低风险", medium: "中风险", high: "高风险", unknown: "未知",
  commerce: "电商业务", social: "闲聊/情绪", capability: "能力咨询", unsupported: "暂不支持",
  execute: "执行", ask_user: "向用户澄清", conversational_response: "自然语言承接",
  graceful_unsupported: "安全降级", safety_deescalation: "安全降级", human_handoff: "转人工",
  readonly_loop: "只读 Agent Loop", workflow: "业务 Workflow",
};

function textValue(value: unknown, fallback = "unknown"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function latestPayload(events: FlowEvent[], type: string): Record<string, unknown> {
  return [...events].reverse().find((event) => event.type === type)?.payload ?? {};
}

function latestRoutingPayload(events: FlowEvent[]): Record<string, unknown> {
  return [...events].reverse().find((event) => event.type === "model_request_succeeded" && event.payload?.purpose === "routing")?.payload ?? {};
}

function hasEvent(events: FlowEvent[], ...types: string[]): boolean {
  return events.some((event) => types.includes(event.type));
}

function nodeState(run: RunSnapshot | null, events: FlowEvent[], node: StageId): FlowState {
  if (!run) return "pending";
  const status = run.status;
  const hasSafety = hasEvent(events, "safety_routed");
  const hasIntent = events.some((event) => event.type === "model_request_succeeded" && event.payload?.purpose === "routing");
  const route = latestPayload(events, "step_completed");
  const hasPolicy = typeof route.response_policy === "string" || ["waiting_user", "waiting_confirmation", "waiting_human", ...TERMINAL_STATUSES].includes(status);
  const hasResponse = hasEvent(events, "assistant_response", "terminal_response_published");

  if (status === "failed") return node === "response" ? "failed" : "done";
  if (status === "waiting_human") return node === "safety" || node === "guard" ? "warning" : "done";
  if (TERMINAL_STATUSES.has(status)) return status === "expired" && node === "response" ? "warning" : "done";
  if (status === "created") return node === "intake" ? "active" : "pending";
  if (status === "routing") {
    if (node === "safety") return hasSafety ? "done" : "active";
    if (node === "domain") return hasIntent ? "done" : "active";
    if (node === "intent") return hasIntent ? "done" : "active";
    if (node === "policy") return hasPolicy ? "active" : "pending";
    return "pending";
  }
  if (WAITING_STATUSES.has(status)) {
    if (node === "guard") return "warning";
    if (node === "response") return hasResponse ? "done" : "active";
    return "done";
  }
  if (status === "committing" || status === "verifying") {
    if (node === "guard") return "active";
    return node === "response" ? "pending" : "done";
  }
  if (node === "executor") return "active";
  if (node === "guard" || node === "response") return "pending";
  return "done";
}

function branchState(run: RunSnapshot | null, events: FlowEvent[], kind: "rag" | "tool" | "skill" | "fallback", evidenceCount: number): FlowState {
  if (!run) return "pending";
  if (kind === "rag") {
    if (hasEvent(events, "rag_retrieval_failed")) return "failed";
    if (evidenceCount > 0) return "done";
    if (hasEvent(events, "rag_retrieval_started", "rag_retrieval_succeeded")) return "warning";
    return "na";
  }
  if (kind === "tool") {
    if (hasEvent(events, "tool_request_failed")) return "failed";
    if (hasEvent(events, "tool_request_started", "tool_request_succeeded")) return TERMINAL_STATUSES.has(run.status) ? "done" : "active";
    return "na";
  }
  if (kind === "skill") {
    const matched = latestPayload(events, "skill_matched");
    if (!Object.keys(matched).length) return "na";
    return matched.mode === "shadow" ? "warning" : "done";
  }
  if (latestPayload(events, "safety_routed").disposition === "blocked") return "warning";
  if (run.status === "waiting_human" || run.status === "waiting_user") return "warning";
  const policy = textValue(latestPayload(events, "step_completed").response_policy);
  if (policy === "conversational_response" || policy === "graceful_unsupported") return "done";
  return "na";
}

function stateText(state: FlowState): string {
  return { pending: "未开始", active: "进行中", done: "已完成", warning: "需关注", failed: "失败", na: "未使用" }[state];
}

function classFor(state: FlowState): string {
  return styles[`flow${state[0].toUpperCase()}${state.slice(1)}`] ?? "";
}

function decisionValue(value: unknown, fallback = "N/A"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function stageEvidence(events: FlowEvent[], node: StageId): string {
  const matches = events.filter((event) => {
    if (node === "intake") return event.type === "run_created";
    if (node === "safety") return event.type === "safety_routed";
    if (node === "domain" || node === "intent") return event.type === "intent_classified" || (event.type.startsWith("model_request") && event.payload?.purpose === "routing");
    if (node === "policy") return event.type === "policy_selected" || event.type === "step_completed";
    if (node === "executor") return event.type === "rag_retrieval_started" || event.type === "rag_retrieval_succeeded" || event.type.startsWith("tool_") || (event.type.startsWith("model_request") && event.payload?.purpose !== "routing");
    if (node === "guard") return event.type.startsWith("guardrail_") || event.type.includes("handoff") || event.type.includes("decision") || event.type === "waiting_for_user";
    return event.type === "assistant_response" || event.type === "terminal_response_published" || event.type === "fallback_activated";
  });
  const latest = matches[matches.length - 1];
  return latest?.id ? `${matches.length} 条证据 · #${latest.id}` : "暂无事件证据";
}

export function AgentFlow({ run, events, evidenceCount }: AgentFlowProps) {
  const safety = latestPayload(events, "safety_routed");
  const classification = latestRoutingPayload(events);
  const route = latestPayload(events, "step_completed");
  const safetyRisk = textValue(safety.risk_level);
  const domain = textValue(safety.domain, textValue(route.request_domain));
  const policy = textValue(route.response_policy);
  const executionMode = textValue(run?.execution_mode, textValue(route.execution_mode, "未选择"));
  const confidence = typeof classification.confidence === "number" ? `${(classification.confidence * 100).toFixed(1)}%` : "N/A";
  const domainConfidence = typeof classification.domain_confidence === "number" ? `${(classification.domain_confidence * 100).toFixed(1)}%` : "N/A";
  const riskConfidence = typeof classification.risk_confidence === "number" ? `${(classification.risk_confidence * 100).toFixed(1)}%` : "N/A";
  const calibrationVersion = decisionValue(classification.confidence_calibration_version);
  const alternativeCount = typeof classification.alternative_count === "number" ? String(classification.alternative_count) : "N/A";
  const skill = latestPayload(events, "skill_matched");
  const routingEvent = [...events].reverse().find((event) => event.type === "model_request_succeeded" && event.payload?.purpose === "routing");
  const shadowEvent = [...events].reverse().find((event) => event.type === "routing_shadow_compared");
  const safetyEvent = [...events].reverse().find((event) => event.type === "safety_routed");
  const terminalDecision = [...events].reverse().find((event) => ["step_completed", "waiting_for_user", "handoff_created", "terminal_response_published"].includes(event.type));
  const routeReason = decisionValue(route.route_reason ?? route.reason_code ?? terminalDecision?.payload?.reason ?? safety.reason_code);
  const decisionCards = [
    { label: "Safety Router", value: `${valueLabels[safetyRisk] ?? safetyRisk} · ${decisionValue(safety.disposition)}`, detail: `原因 ${decisionValue(safety.reason_code)} · 版本 ${decisionValue(safety.detector_version)}`, ref: safetyEvent?.id ? `event #${safetyEvent.id}` : "event N/A", state: safetyRisk === "high" || safetyRisk === "unknown" ? "warning" : "done" },
    { label: "Intent Classifier", value: `${decisionValue(classification.intent)} · ${confidence}`, detail: `${valueLabels[decisionValue(classification.domain)] ?? decisionValue(classification.domain)} · Domain ${domainConfidence} · Risk ${riskConfidence} · 候选 ${alternativeCount}`, ref: routingEvent?.id ? `event #${routingEvent.id}` : "event N/A", state: classification.intent ? "done" : "pending" },
    { label: "Policy Router", value: valueLabels[policy] ?? policy, detail: `原因 ${routeReason} · 执行器 ${valueLabels[executionMode] ?? executionMode}`, ref: terminalDecision?.id ? `event #${terminalDecision.id}` : "event N/A", state: policy === "human_handoff" || policy === "graceful_unsupported" ? "warning" : policy === "unknown" ? "pending" : "done" },
    ...(shadowEvent ? [{ label: "Router Shadow", value: `${decisionValue(shadowEvent.payload?.shadow_intent)} · ${decisionValue(shadowEvent.payload?.shadow_response_policy)}`, detail: `当前 ${decisionValue(shadowEvent.payload?.current_intent)} · 差异 ${decisionValue(shadowEvent.payload?.different, "false")} · 仅观测`, ref: shadowEvent.id ? `event #${shadowEvent.id}` : "event N/A", state: shadowEvent.payload?.different === true ? "warning" : "done" }] : []),
  ];
  const mainNodes: Array<{ id: StageId; label: string; description: string }> = [
    { id: "intake", label: "受理请求", description: "消息与 Run 持久化" },
    { id: "safety", label: "Safety Router", description: "高危与未知风险检查" },
    { id: "domain", label: "Domain Router", description: "commerce / social / capability" },
    { id: "intent", label: "Intent Classifier", description: "意图、领域与置信度" },
    { id: "policy", label: "Policy Router", description: "执行、澄清或降级" },
    { id: "executor", label: "Agent 编排", description: "Loop 或 Workflow 执行" },
    { id: "guard", label: "Guardrail", description: "校验、确认、人工接管" },
    { id: "response", label: "发布回复", description: "结果与证据可见" },
  ];
  const branches = [
    { id: "rag", label: "RAG 检索", detail: evidenceCount > 0 ? `${evidenceCount} 条最终引用证据` : hasEvent(events, "rag_retrieval_started", "rag_retrieval_succeeded") ? "已尝试检索，但最终未引用" : "未使用 / 无检索事件", state: branchState(run, events, "rag", evidenceCount) },
    { id: "tool", label: "工具调用", detail: `${events.filter((event) => event.type === "tool_request_started").length} 次受控调用`, state: branchState(run, events, "tool", evidenceCount) },
    { id: "skill", label: "经验 Skill", detail: typeof skill.mode === "string" ? `${skill.mode} · score ${typeof skill.match_score === "number" ? skill.match_score.toFixed(2) : "N/A"}` : "没有命中", state: branchState(run, events, "skill", evidenceCount) },
    { id: "fallback", label: "安全兜底", detail: policy === "unknown" ? "未触发" : (valueLabels[policy] ?? policy), state: branchState(run, events, "fallback", evidenceCount) },
  ];

  return (
    <section className={styles.flowCard} aria-label="Agent 流程可视化">
      <div className={styles.flowHeader}>
        <div><p className={styles.eyebrow}>Agent Flow · 可审计链路</p><h3>{run ? "本次 Run 的决策与执行路径" : "等待请求启动"}</h3></div>
        <div className={styles.flowHeaderMeta}><span className={styles.flowLegend}>不展示 Prompt、思维链与工具参数</span>{run?.run_id ? <a className={styles.flowHeaderLink} href={`/runs/${encodeURIComponent(run.run_id)}`}>查看完整 Trace ↗</a> : null}</div>
      </div>
      <div className={styles.flowNodes} role="list">
        {mainNodes.map((node, index) => {
          const state = nodeState(run, events, node.id);
          return <div className={styles.flowNodeWrap} key={node.id} role="listitem">
            <div className={`${styles.flowNode} ${classFor(state)}`}>
              <span className={styles.flowNodeMarker} aria-hidden="true">{state === "done" ? "✓" : state === "na" ? "–" : index + 1}</span>
              <strong>{node.label}</strong><span>{node.description}</span><small>{stateText(state)}</small><em className={styles.flowNodeEvidence}>{stageEvidence(events, node.id)}</em>
            </div>
            {index < mainNodes.length - 1 ? <span className={styles.flowArrow} aria-hidden="true">→</span> : null}
          </div>;
        })}
      </div>
      <div className={styles.flowBranch} aria-label="Agent 执行分支">
        <div className={styles.flowBranchHeader}><strong>执行分支</strong><span>编排阶段的可观测子路径</span></div>
        <div className={styles.flowBranchNodes}>
          {branches.map((branch, index) => <div className={styles.flowBranchWrap} key={branch.id}>
            <article className={`${styles.flowBranchNode} ${classFor(branch.state)}`}><strong>{branch.label}</strong><span>{branch.detail}</span><small>{stateText(branch.state)}</small></article>
            {index < branches.length - 1 ? <span className={styles.flowBranchArrow} aria-hidden="true">＋</span> : null}
          </div>)}
        </div>
        <div className={styles.flowStatusLegend} aria-label="流程状态图例"><span><i className={styles.legendDotDone} />已完成</span><span><i className={styles.legendDotActive} />进行中</span><span><i className={styles.legendDotWarning} />需关注</span><span><i className={styles.legendDotNa} />未使用</span></div>
      </div>
      <div className={styles.flowDecisionGrid} aria-label="路由决策证据">
        {decisionCards.map((card) => <article className={`${styles.flowDecisionCard} ${classFor(card.state as FlowState)}`} key={card.label}><div><strong>{card.label}</strong><small>{card.ref}</small></div><b>{card.value}</b><span>{card.detail}</span></article>)}
      </div>
      <div className={styles.flowFacts} aria-label="流程决策事实摘要">
        <span>状态：<strong>{statusLabels[run?.status ?? ""] ?? run?.status ?? "暂无"}</strong></span>
        <span>当前步骤：<strong>{run?.current_step ?? "暂无"}</strong></span>
        <span>风险：<strong>{valueLabels[safetyRisk] ?? safetyRisk}</strong></span>
        <span>领域：<strong>{valueLabels[domain] ?? domain}</strong></span>
        <span>策略：<strong>{valueLabels[policy] ?? policy}</strong></span>
        <span>执行器：<strong>{valueLabels[executionMode] ?? executionMode}</strong></span>
        <span>分类置信度：<strong>{confidence}</strong></span>
        <span>Domain / Risk 校准：<strong>{domainConfidence} / {riskConfidence}</strong></span>
        <span>校准版本：<strong>{calibrationVersion}</strong></span>
        <span>候选数：<strong>{alternativeCount}</strong></span>
        <span>路由原因：<strong>{routeReason}</strong></span>
        <span>步数：<strong>{run?.step_count ?? 0}</strong></span>
        <span>事件/证据：<strong>{events.length} / {evidenceCount}</strong></span>
      </div>
    </section>
  );
}
