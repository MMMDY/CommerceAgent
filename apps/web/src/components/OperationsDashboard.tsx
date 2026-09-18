import { useEffect, useState } from "react";

import styles from "../styles/App.module.css";
import { api, ApiError } from "../api/client";
import { PageState } from "./PageState";
import { TrafficTrendChart } from "./TrafficTrendChart";
import { RELEASE_STATUS_REFRESH_MS } from "../ui/refresh";

type Breakdown = {
  purpose: string;
  provider: string;
  model: string;
  invocation_count: number;
  measured_token_count: number;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_input_tokens: number | null;
  reasoning_tokens: number | null;
  total_tokens: number | null;
  estimated_count: number;
  priced_count: number;
  cost_microusd: number | null;
};
type Trend = { bucket: string; requests: number; completed: number; priced_runs: number; cost_microusd: number | null };
type SafetySummary = { triaged_risk_count: number; blocked_count: number; high_risk_count: number };
type SafetyCategory = { category: string; hit_count: number };
type SafetyCategoryBreakdown = { category: string; hit_count: number; handoff_count: number; false_negative_count: number | null; false_rejection_count: number | null };
type SafetyTrend = { bucket: string; triaged_count: number; blocked_count: number; handoff_count: number };
type SafetyAuditEvent = { audit_event_id: string; event_type: string; created_at: string; payload: { run_id?: string; category?: string; reason_code?: string; detector_version?: string; disposition?: string } };
type RecentRun = { run_id: string; status: string; execution_mode: string; workflow_id: string; route: string; accepted_at: string | null; response_published_at: string | null; total_cost_microusd: number | null; latency_ms: number | null; models: string | null };
type ReleaseSummary = { release_id: string; current_version: string; candidate_version: string; stage: string; status: string; assignment_count: number; shadow_count: number; canary_count: number; current_count: number };
type ReleaseRecord = {
  release_id: string;
  owner_ref?: string;
  current_version: string;
  candidate_version: string;
  stage: string;
  status: string;
  traffic_percent: number;
  observation_ends_at: string | null;
  baseline?: Record<string, unknown>;
  candidate?: Record<string, unknown>;
  stop_reason: string | null;
  rollback_version?: string | null;
  updated_at?: string;
};
type LearningRelease = {
  release_id: string;
  stage: string;
  status: string;
  candidate_version: string;
  traffic_percent: number;
  stop_reason: string | null;
  rollback_version: string | null;
  updated_at: string;
};
type LearningSkill = {
  skill_id: string;
  cluster_key: string;
  status: string;
  source_count: number;
  offline_gate_pass: boolean;
  safety_gate_pass: boolean;
  review_deadline: string | null;
  updated_at: string;
  releases: LearningRelease[];
};
type LearningCluster = {
  cluster_key: string;
  case_count: number;
  max_source_count: number;
  evidence_count: number;
  attributed_case_count: number;
  reviewed_case_count: number;
  latest_category: string | null;
  representative_failure_id: string | null;
  skills: LearningSkill[];
};
type LearningSummary = {
  generated_at: string;
  window_days: number;
  stages: {
    signals: { case_count: number; cluster_count: number };
    clusters: { cluster_count: number; eligible_count: number };
    attribution: { attributed_case_count: number; reviewed_case_count: number; pending_case_count: number };
    skills: { candidate_count: number; pending_review_count: number; approved_count: number; blocked_count: number };
    releases: { release_count: number; active_count: number; canary_count: number; stopped_or_rolled_back_count: number };
  };
  clusters: LearningCluster[];
};
type VersionBreakdown = {
  version: string;
  request_count: number;
  completed_count: number;
  failed_count: number;
  shadow_count: number;
  canary_count: number;
  current_count: number;
  p95_latency_ms: number | null;
  avg_success_cost_microusd: number | null;
  total_tokens: number | null;
  measured_token_count: number;
  route_counts?: Record<string, number> | null;
  skill_match_count: number;
  event_run_count: number;
  safety_hit_count: number;
  safety_high_risk_count: number;
  safety_blocked_count: number;
  handoff_count: number;
  handoff_rate: number | null;
  quality_score: number | null;
  quality_measured_count: number;
};
type OperationsSummary = {
  generated_at: string;
  window_hours: number;
  request_count: number;
  completed_count: number;
  failed_count: number;
  success_rate: number | null;
  measured_latency_count: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
  priced_run_count: number;
  avg_success_cost_microusd: number | null;
  total_cost_microusd: number | null;
  model_breakdown: Breakdown[];
  trend: Trend[];
  safety_summary?: SafetySummary;
  safety_categories?: SafetyCategory[];
  safety_category_breakdown?: SafetyCategoryBreakdown[];
  safety_trend?: SafetyTrend[];
  safety_handoff_count?: number;
  safety_false_negative_count?: number | null;
  safety_false_rejection_count?: number | null;
  release_summary?: ReleaseSummary | null;
  version_breakdown?: VersionBreakdown[];
  recent_runs: RecentRun[];
  available_routes: string[];
  available_models: string[];
  filters?: { tenant_id: string; route: string | null; model: string | null };
};

const duration = (value: number | null) => value === null ? "N/A" : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`;
const cost = (value: number | null) => value === null ? "N/A" : `$${(value / 1_000_000).toFixed(6)}`;
const integer = (value: number | null) => value === null ? "N/A" : new Intl.NumberFormat("zh-CN").format(value);
const ratio = (completed: number, total: number) => total > 0 ? `${(completed / total * 100).toFixed(2)}%` : "N/A";
const percentage = (value: number | null) => value === null ? "N/A" : `${(value * 100).toFixed(2)}%`;
const routes = (value: Record<string, number> | null | undefined) => {
  if (!value || Object.keys(value).length === 0) return "N/A";
  return Object.entries(value).map(([route, count]) => `${route} ×${count}`).join("、");
};
const releaseValue = (record: Record<string, unknown> | undefined, key: string): string => {
  const value = record?.[key];
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  return typeof value === "string" && value.length > 0 ? value : "N/A";
};
const releaseDelta = (baseline: Record<string, unknown> | undefined, candidate: Record<string, unknown> | undefined, key: string, suffix = "") => {
  const before = baseline?.[key];
  const after = candidate?.[key];
  if (typeof before === "number" && typeof after === "number") {
    const delta = after - before;
    return `${releaseValue(baseline, key)}${suffix} → ${releaseValue(candidate, key)}${suffix} (${delta >= 0 ? "+" : ""}${delta.toFixed(3)}${suffix})`;
  }
  if (typeof before === "string" || typeof after === "string") return `${releaseValue(baseline, key)} → ${releaseValue(candidate, key)}`;
  return "N/A";
};

const releaseComparisons = [
  { key: "route", label: "Route", suffix: "" },
  { key: "response_policy", label: "Response Policy", suffix: "" },
  { key: "skill", label: "Skill", suffix: "" },
  { key: "quality", label: "质量", suffix: "" },
  { key: "safety_pass_rate", label: "安全通过率", suffix: "" },
  { key: "p95_e2e_ms", label: "P95 时延", suffix: " ms" },
  { key: "p95_cost_microusd", label: "P95 成本", suffix: " μUSD" },
  { key: "handoff_rate", label: "人工接管率", suffix: "" },
];

function internalApi<T>(path: string, init?: RequestInit): Promise<T> {
  return api<T>(path, {
    ...init,
    headers: { "X-Demo-Actor": "demo-user-001", ...(init?.headers ?? {}) },
  });
}

function operationError(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError && reason.status === 403) return `${fallback}：无权限`;
  return reason instanceof Error ? reason.message : fallback;
}

function branchMetric(data: OperationsSummary, purposes: string[]): string {
  const count = data.model_breakdown.filter((item) => purposes.includes(item.purpose)).reduce((total, item) => total + item.invocation_count, 0);
  return count > 0 ? `${count} 次模型调用` : "逐 Run Trace 可追踪";
}

const flowStages = [
  { id: "intake", label: "请求受理", description: "创建会话与 Run", metric: (data: OperationsSummary) => `${integer(data.request_count)} 个 Run`, state: "measured" },
  { id: "safety", label: "Safety Router", description: "先做风险与安全分流", metric: () => "逐 Run 可追踪", state: "trace" },
  { id: "routing", label: "Intent / Policy", description: "意图、领域与响应策略", metric: () => "逐 Run 可追踪", state: "trace" },
  { id: "execution", label: "Agent 编排", description: "RAG、模型与受控工具", metric: (data: OperationsSummary) => `${integer(data.completed_count)} 个完成`, state: "measured" },
  { id: "guard", label: "Guardrail", description: "校验、确认与人工接管", metric: (data: OperationsSummary) => `${integer(data.failed_count)} 个失败`, state: (data: OperationsSummary) => data.failed_count > 0 ? "attention" : "measured" },
  { id: "publish", label: "回复发布", description: "用户可见结果与审计", metric: (data: OperationsSummary) => data.success_rate === null ? "N/A" : `${(data.success_rate * 100).toFixed(2)}% 完成`, state: "measured" },
];

export function OperationsDashboard() {
  const [windowHours, setWindowHours] = useState(24);
  const [routeFilter, setRouteFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [tenantFilter, setTenantFilter] = useState("demo-tenant");
  const [data, setData] = useState<OperationsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [loading, setLoading] = useState(true);
  const [safetyEvents, setSafetyEvents] = useState<SafetyAuditEvent[]>([]);
  const [safetyAuditError, setSafetyAuditError] = useState<string | null>(null);
  const [releases, setReleases] = useState<ReleaseRecord[]>([]);
  const [releaseError, setReleaseError] = useState<string | null>(null);
  const [learning, setLearning] = useState<LearningSummary | null>(null);
  const [learningError, setLearningError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setRefreshTick((value) => value + 1), RELEASE_STATUS_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null); setForbidden(false);
    const query = new URLSearchParams({ window_hours: String(windowHours), tenant_id: tenantFilter });
    if (routeFilter) query.set("route", routeFilter);
    if (modelFilter) query.set("model", modelFilter);
    internalApi<OperationsSummary>(`/internal/v1/operations/summary?${query.toString()}`, { signal: controller.signal })
      .then(setData)
      .catch((reason: unknown) => { if (!(reason instanceof Error && reason.name === "AbortError")) { setError(operationError(reason, "运营指标加载失败")); setForbidden(reason instanceof ApiError && reason.status === 403); } })
      .finally(() => setLoading(false));
    const learningWindowDays = Math.max(1, Math.ceil(windowHours / 24));
    setLearningError(null);
    internalApi<LearningSummary>(`/internal/v1/operations/learning-summary?window_days=${learningWindowDays}`, { signal: controller.signal })
      .then(setLearning)
      .catch((reason: unknown) => { if (!(reason instanceof Error && reason.name === "AbortError")) setLearningError(operationError(reason, "失败学习链路加载失败")); });
    setSafetyAuditError(null);
    internalApi<{ items: SafetyAuditEvent[] }>("/internal/v1/safety/events?limit=50", { signal: controller.signal })
      .then((result) => setSafetyEvents(result.items))
      .catch((reason: unknown) => { if (!(reason instanceof Error && reason.name === "AbortError")) setSafetyAuditError(operationError(reason, "P0 审计下钻不可用")); });
    setReleaseError(null);
    internalApi<{ items: ReleaseRecord[] }>("/internal/v1/releases", { signal: controller.signal })
      .then((result) => setReleases(result.items))
      .catch((reason: unknown) => { if (!(reason instanceof Error && reason.name === "AbortError")) setReleaseError(operationError(reason, "发布状态加载失败")); });
    return () => controller.abort();
  }, [windowHours, routeFilter, modelFilter, tenantFilter, refreshTick]);

  if (loading) return <PageState kind="loading" title="正在聚合运营指标…" />;
  if (error) return <PageState kind={forbidden ? "forbidden" : "error"} title="运营指标加载失败" detail={error} />;
  if (!data) return <PageState kind="empty" title="暂无运营数据" detail="当前时间范围没有可展示的 Run 数据。" />;
  const latestRelease = releases[0] ?? null;
  const versionBreakdown = data.version_breakdown ?? [];

  return <div className={styles.insightPage}>
    <section className={styles.toolbar}><div><strong>真实运行指标</strong><span>生成于 {new Date(data.generated_at).toLocaleString()} · 只展示授权范围内的脱敏聚合</span></div><div className={styles.toolbarActions}><label>租户<select value={tenantFilter} onChange={(event) => setTenantFilter(event.target.value)}><option value="demo-tenant">demo-tenant</option></select></label><label>时间范围<select value={windowHours} onChange={(event) => setWindowHours(Number(event.target.value))}><option value={24}>最近 24 小时</option><option value={168}>最近 7 天</option><option value={720}>最近 30 天</option></select></label><label>Route<select value={routeFilter} onChange={(event) => setRouteFilter(event.target.value)}><option value="">全部 Route</option>{data.available_routes.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label>模型<select value={modelFilter} onChange={(event) => setModelFilter(event.target.value)}><option value="">全部模型</option>{data.available_models.map((item) => <option key={item} value={item}>{item}</option>)}</select></label></div></section>
    <section className={styles.metricGrid} aria-label="运营指标摘要">
      <article><span>请求量</span><strong>{data.request_count}</strong><small>{data.completed_count} 完成 · {data.failed_count} 失败</small></article>
      <article><span>成功率</span><strong>{data.success_rate === null ? "N/A" : `${(data.success_rate * 100).toFixed(2)}%`}</strong><small>completed / all runs</small></article>
      <article><span>P95 端到端</span><strong>{duration(data.p95_latency_ms)}</strong><small>{data.measured_latency_count}/{data.request_count} 个 Run 可测</small></article>
        <article><span>单次成功成本</span><strong>{cost(data.avg_success_cost_microusd)}</strong><small>{data.priced_run_count}/{data.request_count} 个 Run 完整定价</small></article>
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Safety posture</p><h3>高危类别命中与人工接管</h3></div><span>漏判/误拒绝需人工标注</span></div>
      <div className={styles.metricGrid}><article><span>Safety triage</span><strong>{data.safety_summary?.triaged_risk_count ?? "N/A"}</strong><small>中高风险事件</small></article><article><span>高危命中</span><strong>{data.safety_summary?.high_risk_count ?? "N/A"}</strong><small>确定性/语义风险</small></article><article><span>人工接管</span><strong>{data.safety_handoff_count ?? "N/A"}</strong><small>事件统计</small></article><article><span>漏判 / 误拒绝</span><strong>{data.safety_false_negative_count == null || data.safety_false_rejection_count == null ? "N/A" : `${data.safety_false_negative_count} / ${data.safety_false_rejection_count}`}</strong><small>无复核标签不推断</small></article></div>
      <div className={styles.scoreGrid}>{(data.safety_category_breakdown ?? []).length === 0 ? <p className={styles.empty}>所选时间范围内没有 Safety Router 分类数据。</p> : (data.safety_category_breakdown ?? []).map((item) => <article key={item.category}><div><span>{item.category}</span><strong>{item.hit_count}</strong></div><small>命中 {item.handoff_count} 次人工接管 · 漏判/误拒绝 {item.false_negative_count == null || item.false_rejection_count == null ? "N/A" : `${item.false_negative_count}/${item.false_rejection_count}`}</small></article>)}</div>
      {(data.safety_trend ?? []).length === 0 ? <p className={styles.empty}>暂无 Safety 趋势数据。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><caption>Safety Router 小时趋势</caption><thead><tr><th>时间</th><th>Triaged</th><th>Blocked</th><th>Handoff</th></tr></thead><tbody>{data.safety_trend?.map((item) => <tr key={item.bucket}><td>{new Date(item.bucket).toLocaleString()}</td><td>{item.triaged_count}</td><td>{item.blocked_count}</td><td>{item.handoff_count}</td></tr>)}</tbody></table></div>}
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Admin drill-down</p><h3>P0 Safety 审计事件</h3></div><span>仅管理员 · 脱敏字段</span></div>
      {safetyAuditError ? <p className={styles.flowNote}>审计下钻不可用：{safetyAuditError}；聚合指标仍可查看。</p> : safetyEvents.length === 0 ? <p className={styles.empty}>当前没有可下钻的 P0 审计事件。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><caption>仅返回安全分类、原因码、检测器版本和 Run 引用</caption><thead><tr><th>时间</th><th>Run</th><th>类别</th><th>原因</th><th>检测器</th><th>处置</th></tr></thead><tbody>{safetyEvents.map((event) => <tr key={event.audit_event_id}><td>{new Date(event.created_at).toLocaleString()}</td><td>{event.payload.run_id ? <a href={`/runs/${encodeURIComponent(event.payload.run_id)}`}>{event.payload.run_id.slice(0, 8)}…</a> : "N/A"}</td><td>{event.payload.category ?? "N/A"}</td><td>{event.payload.reason_code ?? "N/A"}</td><td>{event.payload.detector_version ?? "N/A"}</td><td>{event.payload.disposition ?? "N/A"}</td></tr>)}</tbody></table></div>}
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Agent runtime map</p><h3>线上 Agent 流程总览</h3></div><span>总览不替代单 Run Trace</span></div>
      <div className={styles.operationsFlow} role="list">{flowStages.map((stage, index) => { const state = typeof stage.state === "function" ? stage.state(data) : stage.state; return <div className={styles.operationsFlowItem} key={stage.id} role="listitem"><article className={`${styles.operationsFlowNode} ${styles[`operation_${state}`] ?? ""}`}><span>{index + 1}</span><strong>{stage.label}</strong><small>{stage.description}</small><b>{stage.metric(data)}</b></article>{index < flowStages.length - 1 ? <i aria-hidden="true">→</i> : null}</div>; })}</div>
      <div className={styles.operationsBranches} aria-label="线上 Agent 分支可观测性">
        <article><span className={styles.branchIcon}>↗</span><div><strong>RAG / 知识库</strong><small>检索证据在 Run Trace 展示</small></div><b>{branchMetric(data, ["retrieve_knowledge", "search_knowledge"])}</b></article>
        <article><span className={styles.branchIcon}>✦</span><div><strong>模型推理</strong><small>Agent 与 Judge 成本分栏</small></div><b>{integer(data.model_breakdown.reduce((total, item) => total + item.invocation_count, 0))} 次调用</b></article>
        <article><span className={styles.branchIcon}>⚙</span><div><strong>受控工具</strong><small>参数与返回原文不在总览呈现</small></div><b>逐 Run Trace 可追踪</b></article>
        <article><span className={styles.branchIcon}>↺</span><div><strong>失败学习</strong><small>失败簇 → 归因 → Skill 候选</small></div><b><a href="/failures">打开失败归因</a> · <a href="/skills">Skill 队列</a></b></article>
        <article><span className={styles.branchIcon}>⇄</span><div><strong>发布 assignment</strong><small>稳定桶位、Skill 与风险边界可追踪</small></div><b>{data.release_summary ? <><a href="/releases">{data.release_summary.assignment_count} 个 Run</a></> : <a href="/releases">打开发布控制面</a>}</b></article>
      </div>
      <div className={styles.flowStatusLegend} aria-label="运行流程图例"><span><i className={styles.legendDotDone} />聚合已测量</span><span><i className={styles.legendDotActive} />逐 Run 可追踪</span><span><i className={styles.legendDotWarning} />存在关注项</span></div>
      <p className={styles.flowNote}>“逐 Run 可追踪”表示该阶段有事件或决策证据，但当前聚合接口没有单独统计量。下方 Run 列表可进入真实路径、分支、事件和证据；当前筛选会同时作用于聚合和列表。</p>
    </section>
    <LearningPipeline data={learning} error={learningError} />
    <section className={styles.observabilityCard} id="operations-runs">
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Run drill-down</p><h3>最近 Run 与 Agent 流程入口</h3></div><span>{data.recent_runs.length} 条脱敏记录</span></div>
      {data.recent_runs.length === 0 ? <p className={styles.empty}>当前筛选没有可下钻的 Run。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><caption>不展示 Prompt、工具参数、模型输入输出或纠错原文</caption><thead><tr><th>Run</th><th>Route / Workflow</th><th>状态</th><th>模型</th><th>端到端</th><th>成本</th><th>流程</th></tr></thead><tbody>{data.recent_runs.map((item) => <tr key={item.run_id}><td><a href={`/runs/${encodeURIComponent(item.run_id)}`}>{item.run_id.slice(0, 8)}…</a><small>{item.accepted_at ? new Date(item.accepted_at).toLocaleString() : "N/A"}</small></td><td>{item.route}<small>{item.execution_mode} · {item.workflow_id}</small></td><td>{item.status}</td><td>{item.models ?? "N/A"}</td><td>{duration(item.latency_ms)}</td><td>{cost(item.total_cost_microusd)}</td><td><a href={`/runs/${encodeURIComponent(item.run_id)}`}>查看 Trace →</a></td></tr>)}</tbody></table></div>}
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Release comparison</p><h3>Current / Candidate 分流证据</h3></div><span>{data.release_summary ? data.release_summary.stage : "暂无 Active Release"}</span></div>
      {data.release_summary ? <><div className={styles.metricGrid}><article><span>Current</span><strong>{data.release_summary.current_version}</strong><small>{data.release_summary.current_count} 个 Run</small></article><article><span>Candidate</span><strong>{data.release_summary.candidate_version}</strong><small>{data.release_summary.canary_count} 个 Canary · {data.release_summary.shadow_count} 个 Shadow</small></article><article><span>实际候选运行时</span><strong>{latestRelease?.status === "ACTIVE" ? "已登记" : "未确认"}</strong><small>以发布详情和 Runtime 注册为准</small></article><article><span>状态</span><strong>{data.release_summary.status}</strong><small>发布控制面状态</small></article></div><p className={styles.flowNote}>assignment 只说明分桶与观测证据；Candidate 是否改变用户可见结果，必须同时满足 Runtime 注册、风险边界和发布 Gate。</p></> : <p className={styles.empty}>暂无发布控制面记录，无法进行版本对比。</p>}
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Version comparison</p><h3>Current / Candidate 路由与资源差异</h3></div><span>{latestRelease ? `每 15 秒刷新 · ${new Date(latestRelease.updated_at ?? Date.now()).toLocaleTimeString()}` : "暂无发布"}</span></div>
      {releaseError ? <p className={styles.flowNote}>发布详情暂不可用：{releaseError}；运营聚合仍可查看。</p> : latestRelease ? <>
        <div className={styles.releaseMeta}><span>负责人：<strong>{latestRelease.owner_ref ?? "N/A"}</strong></span><span>阶段：<strong>{latestRelease.stage}</strong></span><span>候选流量：<strong>{latestRelease.traffic_percent}%</strong></span><span>观察结束：<strong>{latestRelease.observation_ends_at ? new Date(latestRelease.observation_ends_at).toLocaleString() : "N/A"}</strong></span></div>
        <div className={styles.comparisonTable}><div className={styles.comparisonHeader}><span>指标</span><strong>{latestRelease.current_version}</strong><strong>{latestRelease.candidate_version}</strong><b>Delta / 证据</b></div>{releaseComparisons.map((item) => <div className={styles.comparisonRow} key={item.key}><span>{item.label}</span><strong>{releaseValue(latestRelease.baseline, item.key)}{item.suffix && releaseValue(latestRelease.baseline, item.key) !== "N/A" ? item.suffix : ""}</strong><strong>{releaseValue(latestRelease.candidate, item.key)}{item.suffix && releaseValue(latestRelease.candidate, item.key) !== "N/A" ? item.suffix : ""}</strong><b>{releaseDelta(latestRelease.baseline, latestRelease.candidate, item.key, item.suffix)}</b></div>)}</div>
        {latestRelease.stop_reason ? <p className={styles.flowWarningBox}>已停止：{latestRelease.stop_reason} · 回滚版本：{latestRelease.rollback_version ?? "N/A"}</p> : <p className={styles.flowNote}>缺失的线上聚合指标保持 N/A；只有真实记录同时具备 Current 与 Candidate 时才显示差异。</p>}
      </> : <p className={styles.empty}>暂无发布记录，无法进行版本对比。</p>}
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Version metrics</p><h3>按版本聚合的真实运行指标</h3></div><span>仅统计当前发布 assignment</span></div>
      {versionBreakdown.length === 0 ? <p className={styles.empty}>当前窗口没有可按版本聚合的 Run；未分配记录不会被猜测归入 Candidate。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><caption>版本、流量模式、Route、Quality、Safety、Token、Skill、时延和成本同源聚合</caption><thead><tr><th>版本</th><th>Run</th><th>完成率</th><th>模式</th><th>质量</th><th>Safety</th><th>人工接管</th><th>P95 端到端</th><th>Token</th><th>Skill 命中</th><th>成功成本</th><th>Route 分布</th></tr></thead><tbody>{versionBreakdown.map((item) => <tr key={item.version}><td><strong>{item.version}</strong></td><td>{item.request_count}<small>{item.failed_count} 失败</small></td><td>{ratio(item.completed_count, item.request_count)}</td><td>Current {item.current_count} · Shadow {item.shadow_count} · Canary {item.canary_count}</td><td>{item.quality_score === null ? "N/A" : item.quality_score.toFixed(2)}<small>{item.quality_measured_count} 次 Judge</small></td><td>{item.safety_hit_count}<small>高危 {item.safety_high_risk_count} · 阻断 {item.safety_blocked_count}</small></td><td>{item.handoff_count}<small>{percentage(item.handoff_rate)}</small></td><td>{duration(item.p95_latency_ms)}</td><td>{integer(item.total_tokens)}<small>{item.measured_token_count} 次有 usage</small></td><td>{item.skill_match_count}</td><td>{cost(item.avg_success_cost_microusd)}</td><td>{routes(item.route_counts)}</td></tr>)}</tbody></table></div>}
      <p className={styles.flowNote}>`unassigned` 表示窗口内没有匹配当前发布 assignment 的 Run；该类不会被强行解释为 Current 或 Candidate。质量分数在当前运行接口没有独立 Judge 标注时显示 N/A；Safety 与人工接管只统计已落库事件，不把缺失标注推断成通过。</p>
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>SLO baseline</p><h3>时延分位数</h3></div><span>基线冻结前仅观测</span></div>
      <div className={styles.percentileGrid}><article><span>P50</span><strong>{duration(data.p50_latency_ms)}</strong></article><article><span>P95</span><strong>{duration(data.p95_latency_ms)}</strong></article><article><span>P99</span><strong>{duration(data.p99_latency_ms)}</strong></article><article><span>总成本</span><strong>{cost(data.total_cost_microusd)}</strong></article></div>
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Traffic</p><h3>每小时请求趋势</h3></div><span>绿色为完成数</span></div>
      {data.trend.length === 0 ? <p className={styles.empty}>所选时间范围内没有 Run。</p> : <><TrafficTrendChart points={data.trend} /><table className={styles.dataTable}><caption>每小时趋势语义化数据表</caption><thead><tr><th>时间</th><th>请求</th><th>完成</th><th>已定价 Run</th><th>成本</th></tr></thead><tbody>{data.trend.map((item) => <tr key={item.bucket}><td>{new Date(item.bucket).toLocaleString()}</td><td>{item.requests}</td><td>{item.completed}</td><td>{item.priced_runs}</td><td>{cost(item.cost_microusd)}</td></tr>)}</tbody></table></>}
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Cost allocation</p><h3>模型用途 / Provider 成本拆分</h3></div><span>Judge 与 Agent 不混算</span></div>
      {data.model_breakdown.length === 0 ? <p className={styles.empty}>所选时间范围内没有模型调用。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><thead><tr><th>用途</th><th>模型</th><th>调用</th><th>Token 可测</th><th>输入</th><th>输出</th><th>总 Token</th><th>估算 usage</th><th>已定价</th><th>成本</th></tr></thead><tbody>{data.model_breakdown.map((item) => <tr key={`${item.purpose}-${item.provider}-${item.model}`}><td>{item.purpose}</td><td>{item.provider}/{item.model}</td><td>{item.invocation_count}</td><td>{item.measured_token_count}/{item.invocation_count}</td><td>{integer(item.input_tokens)}</td><td>{integer(item.output_tokens)}</td><td>{integer(item.total_tokens)}</td><td>{item.estimated_count}</td><td>{item.priced_count}/{item.invocation_count}</td><td>{cost(item.cost_microusd)}</td></tr>)}</tbody></table></div>}
    </section>
  </div>;
}

function LearningPipeline({ data, error }: { data: LearningSummary | null; error: string | null }) {
  if (error) {
    return <section className={styles.observabilityCard} aria-label="失败学习链路"><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Failure learning</p><h3>异常指标 → 失败簇 → 归因 → Skill → 发布</h3></div><span>状态不可用</span></div><p className={styles.flowNote}>后端审计链路加载失败：{error}。页面不使用其它页面数据拼接替代。</p></section>;
  }
  if (!data) {
    return <section className={styles.observabilityCard} aria-label="失败学习链路"><PageState kind="loading" title="正在读取失败学习链路…" /></section>;
  }
  const stages = [
    { label: "异常指标", detail: `${data.stages.signals.case_count} 个失败信号`, href: "/failures", state: data.stages.signals.case_count > 0 ? styles.flowActive : styles.flowPendingBox },
    { label: "失败簇", detail: `${data.stages.clusters.cluster_count} 个 · ${data.stages.clusters.eligible_count} 个达来源门槛`, href: "/failures", state: data.stages.clusters.eligible_count > 0 ? styles.flowPassed : styles.flowPendingBox },
    { label: "归因复核", detail: `${data.stages.attribution.reviewed_case_count}/${data.stages.attribution.attributed_case_count} 已复核`, href: "/failures", state: data.stages.attribution.pending_case_count > 0 ? styles.flowBlocked : styles.flowPassed },
    { label: "Skill 候选", detail: `${data.stages.skills.candidate_count} 个 · ${data.stages.skills.pending_review_count} 待审批`, href: "/skills", state: data.stages.skills.pending_review_count > 0 ? styles.flowActive : styles.flowPendingBox },
    { label: "Canary", detail: `${data.stages.releases.canary_count} 个发布处于 Canary`, href: "/releases", state: data.stages.releases.canary_count > 0 ? styles.flowActive : styles.flowPendingBox },
    { label: "停止 / 回滚", detail: `${data.stages.releases.stopped_or_rolled_back_count} 个有停止记录`, href: "/releases", state: data.stages.releases.stopped_or_rolled_back_count > 0 ? styles.flowBlocked : styles.flowPendingBox },
  ];
  return <section className={styles.observabilityCard} aria-label="失败学习链路">
    <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Audited failure learning</p><h3>异常指标 → 失败簇 → 归因 → Skill → Canary / 回滚</h3></div><span>窗口 {data.window_days} 天 · 后端审计投影</span></div>
    <div className={styles.approvalFlow}>{stages.map((stage, index) => <div className={styles.approvalFlowFragment} key={stage.label}><a className={stage.state} href={stage.href}><span>{index + 1}</span><strong>{stage.label}</strong><small>{stage.detail}</small></a>{index < stages.length - 1 ? <i aria-hidden="true">→</i> : null}</div>)}</div>
    <p className={styles.flowNote}>连线只表示服务端存在对应阶段数据；具体关联只在下表展示。没有 assignment 或发布审计关联时显示“暂无可证明关联”，不会把 Skill 页面存在误认为已 Canary。</p>
    {data.clusters.length === 0 ? <p className={styles.empty}>窗口内没有失败簇，链路暂无可下钻数据。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><caption>每个 cluster 的后端可证明关联；不展示原始 Prompt、回复或纠错文本</caption><thead><tr><th>失败簇</th><th>信号 / 归因</th><th>Skill</th><th>Canary / 停止</th></tr></thead><tbody>{data.clusters.map((cluster) => <tr key={cluster.cluster_key}><td>{cluster.representative_failure_id ? <a href={`/failures/${encodeURIComponent(cluster.representative_failure_id)}`}>{cluster.cluster_key}</a> : cluster.cluster_key}<small>{cluster.case_count} 个案例 · 独立证据 {cluster.evidence_count}</small></td><td>{cluster.latest_category ?? "未归因"}<small>归因 {cluster.attributed_case_count} · 人工复核 {cluster.reviewed_case_count}</small></td><td>{cluster.skills.length === 0 ? <span className={styles.muted}>暂无候选</span> : cluster.skills.map((skill) => <div key={skill.skill_id}><a href={`/skills/${encodeURIComponent(skill.skill_id)}`}>{skill.status}</a><small>来源 {skill.source_count} · {skill.offline_gate_pass && skill.safety_gate_pass ? "Gate 通过" : "Gate 未通过"}</small></div>)}</td><td>{cluster.skills.flatMap((skill) => skill.releases).length === 0 ? <span className={styles.muted}>暂无可证明关联</span> : cluster.skills.flatMap((skill) => skill.releases).map((release) => <div key={release.release_id}><a href={`/releases/${encodeURIComponent(release.release_id)}`}>{release.stage} / {release.status}</a><small>{release.stop_reason ?? (release.rollback_version ? `回滚 ${release.rollback_version}` : `${release.traffic_percent}% 流量`)}</small></div>)}</td></tr>)}</tbody></table></div>}
  </section>;
}
