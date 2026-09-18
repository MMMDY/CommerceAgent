import { useEffect, useMemo, useState } from "react";

import styles from "../styles/App.module.css";
import { PageState } from "./PageState";
import { StatusTag } from "./StatusTag";
import { api, ApiError } from "../api/client";
import { formatDurationMs, formatNumber, formatUsdMicros } from "../ui/formatters";

type FlowNode = { id: string; label: string; description: string; state: string };
type Timing = { id: string; label: string; duration_ms: number | null; state: string };
type TokenUsage = {
  input_tokens: number | null;
  output_tokens: number | null;
  cached_input_tokens: number | null;
  reasoning_tokens: number | null;
  total_tokens: number | null;
  estimated: boolean;
};
type ModelInvocation = {
  id: string;
  step_id: string;
  purpose: string;
  provider: string;
  model: string;
  status: string;
  error_code: string | null;
  latency_ms: number | null;
  first_token_latency_ms: number | null;
  token_usage: TokenUsage;
  cost_microusd: number | null;
  priced: boolean;
};
type ToolInvocation = {
  id: string;
  step_id: string;
  tool_name: string;
  risk_level: string;
  status: string;
  attempt_no: number;
  error_code: string | null;
  latency_ms: number | null;
};
type TraceEvent = {
  id: number;
  type: string;
  step_id: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};
type Evidence = { evidence_id: string; source_uri: string; version: string; excerpt: string };
type Visualization = {
  run_id: string;
  status: string;
  current_step: string;
  nodes: FlowNode[];
  decision: Record<string, string>;
  summary: {
    event_count: number;
    evidence_count: number;
    model_invocation_count: number;
    tool_invocation_count: number;
    total_tokens: number | null;
    token_usage_complete: boolean;
    usage_estimated_count: number;
    total_cost_microusd: number | null;
    pricing_complete: boolean;
  };
  timings: Timing[];
  model_invocations: ModelInvocation[];
  tool_invocations: ToolInvocation[];
};

const decisionLabels: Record<string, string> = {
  low: "低风险", medium: "中风险", high: "高风险", unknown: "未知",
  commerce: "电商业务", social: "闲聊/情绪", capability: "能力咨询", unsupported: "暂不支持",
  execute: "执行", ask_user: "向用户澄清", conversational_response: "自然语言承接",
  graceful_unsupported: "安全降级", human_handoff: "转人工", readonly_loop: "只读 Agent Loop",
};

const traceLabels: Record<string, string> = {
  run_created: "Run 已创建", safety_routed: "Safety Router 完成", skill_matched: "经验 Skill 命中", model_request_started: "模型调用开始",
  model_request_succeeded: "模型调用完成", model_request_failed: "模型调用失败", step_completed: "编排步骤完成",
  tool_request_started: "工具调用开始", tool_request_succeeded: "工具调用完成", tool_request_failed: "工具调用失败",
  assistant_response: "Agent 生成回复", terminal_response_published: "回复已发布", waiting_for_user: "等待用户补充",
  handoff_created: "已转人工", handoff_resolved: "人工处理完成", release_assigned: "发布版本已分配", failed: "Run 失败",
};

function traceLabel(type: string): string { return traceLabels[type] ?? type; }

function traceStage(type: string, payload: Record<string, unknown> = {}): string {
  if (type === "run_created") return "受理";
  if (type === "safety_routed" || (type.startsWith("model_request") && (payload.purpose === "routing" || payload.purpose === "intent_classification"))) return "识别与路由";
  if (type === "release_assigned") return "上线与成本";
  if (type.startsWith("tool_") || type === "model_request_failed" || type === "step_completed") return "Agent 执行";
  if (type.includes("handoff") || type.includes("mutation") || type.includes("commit") || type.includes("verified") || type.includes("decision")) return "Guardrail";
  if (type.includes("response") || type === "assistant_response") return "回复发布";
  return "Agent 执行";
}

function traceTone(type: string): string {
  if (type.includes("failed") || type === "failed") return "danger";
  if (type.includes("handoff") || type.includes("waiting") || type === "safety_routed") return "warning";
  if (type.includes("succeeded") || type.includes("published") || type === "assistant_response") return "success";
  return "neutral";
}

function safeTraceDetail(payload: Record<string, unknown>): string {
  const keys = ["purpose", "outcome", "status", "error_code", "reason_code", "disposition", "intent", "domain", "request_domain", "request_risk_level", "response_policy", "execution_mode", "confidence", "domain_confidence", "risk_confidence", "confidence_calibration_version", "alternative_count", "tool", "current_route", "candidate_route", "current_response_policy", "candidate_response_policy", "current_skill", "candidate_skill", "estimated_cost_delta_microusd", "candidate_runtime_available", "candidate_execution_allowed", "observation_only", "retryable", "fallback_used", "mode", "match_score"];
  const values = keys.filter((key) => key in payload).map((key) => `${key}=${String(payload[key])}`);
  return values.length > 0 ? values.join(" · ") : "仅展示事件类型与步骤，详细参数已隐藏";
}

function decisionText(value: string | undefined): string {
  return value ? (decisionLabels[value] ?? value) : "N/A";
}

function decisionState(value: string | undefined, warning = false): string {
  if (!value) return "not_applicable";
  return warning || value === "high" || value === "medium" || value === "human_handoff" ? "warning" : "completed";
}

function stateLabel(state: string): string {
  return ({
    completed: "已完成",
    active: "进行中",
    pending: "未开始",
    warning: "需确认",
    failed: "失败",
    not_applicable: "不适用",
  } as Record<string, string>)[state] ?? state;
}

export function RunInsight({ runId }: { runId: string }) {
  const [data, setData] = useState<Visualization | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [partialError, setPartialError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [traceUnavailable, setTraceUnavailable] = useState(false);
  const [evidenceUnavailable, setEvidenceUnavailable] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setPartialError(null);
    setForbidden(false);
    setTraceUnavailable(false);
    setEvidenceUnavailable(false);
    const load = async () => {
      try {
        const visualization = await api<Visualization>(`/v1/runs/${encodeURIComponent(runId)}/visualization`, { signal: controller.signal });
        setData(visualization);
        const [traceResult, evidenceResult] = await Promise.allSettled([
          api<TraceEvent[]>(`/v1/runs/${encodeURIComponent(runId)}/timeline`, { signal: controller.signal }),
          api<Evidence[]>(`/v1/runs/${encodeURIComponent(runId)}/evidence`, { signal: controller.signal }),
        ]);
        const partials: string[] = [];
        if (traceResult.status === "fulfilled") setTrace(traceResult.value);
        else { setTraceUnavailable(true); partials.push(traceResult.reason instanceof ApiError && traceResult.reason.status === 403 ? "事件链无权限" : "事件链暂不可用"); }
        if (evidenceResult.status === "fulfilled") setEvidence(evidenceResult.value);
        else { setEvidenceUnavailable(true); partials.push(evidenceResult.reason instanceof ApiError && evidenceResult.reason.status === 403 ? "RAG 证据无权限" : "RAG 证据暂不可用"); }
        if (partials.length > 0) setPartialError(`${partials.join("、")}；其余 Run 证据仍可查看`);
      } catch (reason) {
        if (reason instanceof Error && reason.name === "AbortError") return;
        if (reason instanceof ApiError && reason.status === 403) setForbidden(true);
        setError(reason instanceof Error ? reason.message : "Run 数据加载失败");
      } finally {
        setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [runId, reload]);

  const maxTiming = useMemo(
    () => Math.max(1, ...(data?.timings.filter((item) => item.id !== "e2e").map((item) => item.duration_ms ?? 0) ?? [0])),
    [data],
  );

  const decisionChain = data ? [
    { id: "safety", label: "Safety Router", value: data.decision.request_risk_level, detail: "内容与账户风险", state: decisionState(data.decision.request_risk_level, data.decision.request_risk_level === "unknown") },
    { id: "domain", label: "Request Domain", value: data.decision.request_domain, detail: "请求所属领域", state: data.decision.request_domain ? "completed" : "not_applicable" },
    { id: "intent", label: "Intent Classifier", value: data.decision.intent, detail: data.decision.classification_confidence ? `意图识别 · 置信度 ${Number(data.decision.classification_confidence) * 100}%` : "意图识别结果", state: data.decision.intent ? "completed" : "not_applicable" },
    { id: "policy", label: "Response Policy", value: data.decision.response_policy, detail: "代码约束的响应策略", state: decisionState(data.decision.response_policy) },
    { id: "executor", label: "Executor", value: data.decision.route, detail: "最终选择的业务路径", state: data.decision.route ? "completed" : "not_applicable" },
  ] : [];
  const visibleTrace = trace.slice(-20);

  if (loading) return <PageState kind="loading" title="正在读取 Run 可观测数据…" />;
  if (error) return <PageState kind={forbidden ? "forbidden" : "error"} title="无法加载 Run" detail={error} action={{ label: "重试", onClick: () => setReload((value) => value + 1) }} />;
  if (!data) return <PageState kind="empty" title="暂无 Run 数据" />;

  return (
    <div className={styles.insightPage}>
      <section className={styles.runHero}>
        <div><p className={styles.eyebrow}>Run · {data.run_id}</p><h3>执行路径与资源消耗</h3><p>当前步骤：{data.current_step}</p></div>
        <StatusTag value={data.status} />
      </section>
      {partialError ? <PageState kind="partial" title="Run 展示不完整" detail={partialError} /> : null}

      <section className={styles.metricGrid} aria-label="Run 指标摘要">
        <article><span>端到端时延</span><strong>{formatDurationMs(data.timings.find((item) => item.id === "e2e")?.duration_ms ?? null)}</strong><small>受理至用户可见回复</small></article>
        <article><span>总 Token</span><strong>{formatNumber(data.summary.total_tokens)}</strong><small>{data.summary.token_usage_complete ? "Provider 已完整返回" : "存在缺失，显示 N/A"}</small></article>
        <article><span>Agent 成本</span><strong>{formatUsdMicros(data.summary.total_cost_microusd)}</strong><small>{data.summary.pricing_complete ? "按命中价格版本估算" : "存在未定价调用"}</small></article>
        <article><span>模型 / 工具调用</span><strong>{data.summary.model_invocation_count} / {data.summary.tool_invocation_count}</strong><small>{data.summary.usage_estimated_count} 次 usage 为估算</small></article>
      </section>

      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Decision chain</p><h3>Agent 决策链</h3></div><span>安全边界先于执行</span></div>
        <div className={styles.decisionChain} role="list">
          {decisionChain.map((step, index) => <div className={styles.decisionChainItem} key={step.id} role="listitem">
            <article className={`${styles.decisionChainStep} ${styles[`topology_${step.state}`] ?? ""}`}><span>{index + 1}</span><strong>{step.label}</strong><small>{step.detail}</small><b>{decisionText(step.value)}</b></article>
            {index < decisionChain.length - 1 ? <i aria-hidden="true">→</i> : null}
          </div>)}
        </div>
        <div className={styles.executionLane} aria-label="执行分支摘要">
          <article><strong>RAG 检索</strong><span>{data.timings.find((item) => item.id === "rag")?.state === "not_applicable" ? "未使用" : `${data.summary.evidence_count} 条证据`}</span></article>
          <article><strong>工具调用</strong><span>{data.summary.tool_invocation_count} 次 · {data.timings.find((item) => item.id === "tool")?.state === "measured" ? "已测时延" : "无完整时延"}</span></article>
          <article><strong>经验 Skill</strong><span>{data.summary.event_count > 0 && trace.some((event) => event.type === "skill_matched") ? "已记录命中" : "未命中"}</span></article><article><strong>结果保护</strong><span>{data.status === "waiting_human" ? "已转人工" : data.status === "failed" ? "失败兜底" : "已保留审计证据"}</span></article>
        </div>
      </section>

      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Orchestration</p><h3>Agent 执行拓扑</h3></div><span>仅展示可审计决策</span></div>
        <div className={styles.topology} role="list">
          {data.nodes.map((node, index) => <div className={styles.topologyItem} key={node.id} role="listitem"><article className={`${styles.topologyNode} ${styles[`topology_${node.state}`] ?? ""}`}><span>{index + 1}</span><strong>{node.label}</strong><p>{node.description}</p><small>{stateLabel(node.state)}</small></article>{index < data.nodes.length - 1 ? <i aria-hidden="true">→</i> : null}</div>)}
        </div>
        <dl className={styles.decisionFacts}>
          {Object.keys(data.decision).length === 0 ? <div><dt>路由决策</dt><dd>unknown</dd></div> : Object.entries(data.decision).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
          <div><dt>事件</dt><dd>{data.summary.event_count}</dd></div><div><dt>证据</dt><dd>{data.summary.evidence_count}</dd></div>
        </dl>
      </section>

      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Event path</p><h3>实际事件路径</h3></div><span>{trace.length} 个事件 · 最近展示 {visibleTrace.length} 个</span></div>
        {traceUnavailable ? <PageState kind="partial" title="事件链暂不可用" detail="当前没有足够权限或接口失败，未将空结果解释为无事件。" /> : visibleTrace.length === 0 ? <p className={styles.empty}>暂无事件。事件写入后会在这里展示真实执行顺序。</p> : <div className={styles.tracePath} role="list">{visibleTrace.map((event, index) => <div className={styles.tracePathItem} key={event.id} role="listitem"><article className={`${styles.tracePathNode} ${styles[`trace_${traceTone(event.type)}`] ?? ""}`}><div><span>#{event.id}</span><small>{traceStage(event.type, event.payload)}</small></div><strong>{traceLabel(event.type)}</strong><p>{event.step_id}</p><em>{safeTraceDetail(event.payload)}</em><time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleTimeString()}</time></article>{index < visibleTrace.length - 1 ? <i aria-hidden="true">→</i> : null}</div>)}</div>}
      </section>

      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Latency</p><h3>阶段时延瀑布</h3></div><span>并行阶段不可直接相加</span></div>
        <div className={styles.waterfall}>
          {data.timings.map((item) => <div className={styles.waterfallRow} key={item.id}><span>{item.label}</span><div><i className={item.state === "measured" ? styles.barMeasured : styles.barUnknown} style={{ width: item.duration_ms === null ? "100%" : `${Math.max(3, item.duration_ms / maxTiming * 100)}%` }} /></div><strong>{item.state === "not_applicable" ? "不适用" : formatDurationMs(item.duration_ms)}</strong></div>)}
        </div>
        <table className={styles.dataTable}><caption>阶段时延语义化数据表</caption><thead><tr><th>阶段</th><th>状态</th><th>时延</th></tr></thead><tbody>{data.timings.map((item) => <tr key={item.id}><td>{item.label}</td><td>{item.state}</td><td>{item.state === "not_applicable" ? "不适用" : formatDurationMs(item.duration_ms)}</td></tr>)}</tbody></table>
      </section>

      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Model calls</p><h3>模型调用与 Token / 成本</h3></div><span>{data.model_invocations.length} 次调用</span></div>
        {data.model_invocations.length === 0 ? <p className={styles.empty}>本 Run 没有模型调用记录。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><thead><tr><th>用途</th><th>模型</th><th>状态</th><th>时延</th><th>TTFT</th><th>输入</th><th>缓存输入</th><th>输出</th><th>推理</th><th>总 Token</th><th>成本</th></tr></thead><tbody>{data.model_invocations.map((item) => <tr key={item.id}><td>{item.purpose}<small>{item.step_id}</small></td><td>{item.provider}/{item.model}</td><td>{item.status}{item.error_code ? <small>{item.error_code}</small> : null}</td><td>{formatDurationMs(item.latency_ms)}</td><td>{formatDurationMs(item.first_token_latency_ms)}</td><td>{formatNumber(item.token_usage.input_tokens)}</td><td>{formatNumber(item.token_usage.cached_input_tokens)}</td><td>{formatNumber(item.token_usage.output_tokens)}</td><td>{formatNumber(item.token_usage.reasoning_tokens)}</td><td>{formatNumber(item.token_usage.total_tokens)}{item.token_usage.estimated ? <small>估算</small> : null}</td><td>{formatUsdMicros(item.cost_microusd)}{!item.priced ? <small>未定价</small> : null}</td></tr>)}</tbody></table></div>}
      </section>

      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Tools</p><h3>工具与安全边界</h3></div><span>不展示参数与返回原文</span></div>
        {data.tool_invocations.length === 0 ? <p className={styles.empty}>本 Run 没有工具调用。</p> : <table className={styles.dataTable}><thead><tr><th>工具</th><th>步骤</th><th>风险</th><th>尝试</th><th>状态</th><th>时延</th></tr></thead><tbody>{data.tool_invocations.map((item) => <tr key={item.id}><td>{item.tool_name}</td><td>{item.step_id}</td><td>{item.risk_level}</td><td>{item.attempt_no}</td><td>{item.status}{item.error_code ? <small>{item.error_code}</small> : null}</td><td>{formatDurationMs(item.latency_ms)}</td></tr>)}</tbody></table>}
      </section>

      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>RAG evidence</p><h3>最终回答引用的知识证据</h3></div><span>{evidence.length} 条授权证据</span></div>
        {evidenceUnavailable ? <PageState kind="partial" title="RAG 证据暂不可用" detail="证据接口失败或无权限；不能据此判断本 Run 未执行检索。" /> : evidence.length === 0 ? <p className={styles.empty}>本 Run 没有最终引用的 RAG 证据；这不代表没有尝试检索。</p> : <div className={styles.evidenceGrid}>{evidence.map((item) => <article className={styles.evidenceCard} key={item.evidence_id}><code>{item.source_uri}</code><small>版本 {item.version} · {item.evidence_id}</small><p>{item.excerpt}</p></article>)}</div>}
      </section>
    </div>
  );
}
