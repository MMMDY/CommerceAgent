import { useEffect, useMemo, useState } from "react";

import styles from "../styles/App.module.css";
import { PageState } from "./PageState";
import { StatusTag } from "./StatusTag";
import { ApiError } from "../api/client";
import { RELEASE_STATUS_REFRESH_MS } from "../ui/refresh";

type Page = "failures" | "failure" | "skills" | "skill" | "releases" | "release";
type Attribution = { deterministic_category?: string | null; llm_category?: string | null; confidence?: number | null; evidence_refs?: string[]; review_status?: string; rationale_redacted?: string | null; reviewed_category?: string | null; reviewed_by?: string | null; reviewed_at?: string | null; review_note_redacted?: string | null };
type Failure = { failure_id: string; signal: string; severity: string; source: string; run_id: string | null; eval_run_id?: string | null; case_id?: string | null; status: string; cluster_key: string; summary_redacted: string; source_count: number; trace_refs?: string[]; updated_at: string; attribution?: Attribution | null };
type FailureAggregate = { cluster_key?: string; category?: string; severity?: string; status?: string; case_count: number; max_source_count?: number };
type FailureTrend = { bucket: string; case_count: number; critical_count: number; reviewed_count: number };
type FailureSummary = { window_days: number; top_clusters: FailureAggregate[]; taxonomy: FailureAggregate[]; severity: FailureAggregate[]; status: FailureAggregate[]; trend: FailureTrend[] };
type SkillVersion = { skill_version_id: string; version_no: number; definition_hash: string; status: string; approved_by?: string | null; approved_at?: string | null; activated_at?: string | null; expires_at: string | null; definition?: Record<string, unknown> };
type SkillEvaluation = { evaluation_id: string; skill_id: string; skill_version_id?: string | null; dataset_hash: string; before: Record<string, number | null>; after: Record<string, number | null>; safety_result: "pass" | "fail" | "incomplete"; cost_delta_microusd: number | null; latency_delta_ms: number | null; gate_pass: boolean; judge_disagreement_count: number; created_at?: string };
type SkillControl = { tenant_id: string; matching_enabled: boolean; can_mutate: boolean };
type Skill = { skill_id: string; scope_type: string; scope_value: string; status: string; source_count: number; cluster_key: string; trigger: Record<string, unknown>; strategy: Record<string, unknown>; provenance?: Record<string, unknown>; versions?: SkillVersion[]; evaluations?: SkillEvaluation[]; evaluation_gate_pass?: boolean | null; evaluation_safety_result?: string | null; evaluation_judge_disagreement_count?: number | null; offline_gate_pass: boolean; safety_gate_pass: boolean; review_deadline: string | null };
type ReleaseAssignment = { assignment_id: string; run_id: string; selected_version: string; mode: string; bucket: number; traffic_percent: number; risk_level: string; risk_hint: string; reason: string; comparison?: Record<string, unknown> };
type ReleaseEvent = { event_id: string; event_type: string; actor_ref?: string; created_at: string; payload?: Record<string, unknown> };
type Release = { release_id: string; owner_ref?: string; current_version: string; candidate_version: string; stage: string; status: string; traffic_percent: number; observation_started_at: string | null; observation_ends_at: string | null; baseline?: Record<string, unknown>; candidate?: Record<string, unknown>; gates: Record<string, unknown>; stop_reason: string | null; rollback_version?: string | null; updated_at?: string; assignments?: ReleaseAssignment[]; events?: ReleaseEvent[] };

const copy: Record<Page, { eyebrow: string; title: string; description: string }> = {
  failures: { eyebrow: "Failure learning", title: "失败归因流水线", description: "失败信号先脱敏、聚类和归因；达到跨来源门槛后才允许形成候选经验。" },
  failure: { eyebrow: "Failure detail", title: "单次失败证据链", description: "自动归因是建议，不等同于真人结论；原始用户文本与隐藏推理永不展示。" },
  skills: { eyebrow: "Experience registry", title: "经验 Skill 受控生命周期", description: "自动化评测无人审批时，Skill 只能停留在 PENDING_REVIEW，不能自动激活。" },
  skill: { eyebrow: "Skill detail", title: "Skill 证据与审批", description: "离线门禁通过后仍需要真人批准，之后才可进入 Canary。" },
  releases: { eyebrow: "Progressive delivery", title: "Shadow → Canary → 生产", description: "发布由评测证据、质量、安全和成本门禁共同驱动，异常时自动停止。" },
  release: { eyebrow: "Release detail", title: "发布证据包", description: "展示候选版本、流量阶段、观测窗口、Gate 和停止审计。" },
};
const labels: Record<string, string> = { CANDIDATE: "候选", PENDING_REVIEW: "待人工审批", APPROVED: "已批准", CANARY: "Canary", ACTIVE: "生产中", REJECTED: "已拒绝", EXPIRED: "已过期", ROLLED_BACK: "已回滚", SHADOW: "Shadow", CANARY_5: "5%", CANARY_25: "25%", CANARY_50: "50%", FULL: "100%", STOPPED: "已停止" };
const showStatus = (value: string | undefined) => value ? (labels[value] ?? gateLabel[value] ?? `未知状态：${value}`) : "N/A";
const showDate = (value: string | null | undefined) => value ? new Date(value).toLocaleString() : "N/A";
const showMetric = (value: number | null | undefined, suffix = "") => value === null || value === undefined ? "N/A" : `${Number.isInteger(value) ? value : value.toFixed(3)}${suffix}`;
const showValue = (value: unknown, suffix = "") => typeof value === "number" ? showMetric(value, suffix) : typeof value === "string" && value.length > 0 ? value : "N/A";
const showValueDelta = (before: unknown, after: unknown, suffix = "") => typeof before === "number" && typeof after === "number" ? `${showMetric(before, suffix)} → ${showMetric(after, suffix)} (${after - before >= 0 ? "+" : ""}${showMetric(after - before, suffix)})` : typeof before === "string" || typeof after === "string" ? `${showValue(before)} → ${showValue(after)}` : "N/A";
const showDelta = (before: number | null | undefined, after: number | null | undefined, suffix = "") => showValueDelta(before, after, suffix);
const gateLabel: Record<string, string> = { quality: "质量", safety: "安全", safety_pass_rate: "安全通过率", p95_e2e_ms: "P95 时延", p95_cost_microusd: "P95 成本", handoff_rate: "人工接管率", terminal_response_coverage: "终态回复覆盖率", baseline: "基线" };

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", "X-Demo-Actor": "demo-user-001" }, ...init });
  if (!response.ok) {
    let detail: unknown;
    try { detail = await response.json(); } catch { /* preserve the status */ }
    const message = typeof detail === "object" && detail !== null && "detail" in detail
      ? String((detail as { detail: unknown }).detail)
      : `接口请求失败（${response.status}）`;
    throw new ApiError(response.status, message, detail);
  }
  return response.json() as Promise<T>;
}

function errorState(title: string, reason: unknown) {
  const message = reason instanceof Error ? reason.message : "接口请求失败";
  return <PageState kind={reason instanceof ApiError && reason.status === 403 ? "forbidden" : "error"} title={title} detail={message} />;
}

function ProcessFlow({ page }: { page: Page }) {
  const runtime = [
    { id: "intake", label: "受理", detail: "消息 / Run" },
    { id: "route", label: "Safety → Intent", detail: "风险、领域、意图" },
    { id: "policy", label: "Policy Router", detail: "执行 / 澄清 / 降级" },
    { id: "execute", label: "Agent 编排", detail: "RAG · Tool · Skill" },
    { id: "guard", label: "Guardrail", detail: "校验 / 接管" },
    { id: "response", label: "回复发布", detail: "证据 / 终态" },
  ];
  const learning = [
    { id: "evals", label: "评测", detail: "Hard + Judge", href: "/evals" },
    { id: "failures", label: "失败归因", detail: "聚类 / 复核", href: "/failures" },
    { id: "skills", label: "经验 Skill", detail: "审批 / TTL", href: "/skills" },
    { id: "releases", label: "渐进发布", detail: "Shadow → Canary", href: "/releases" },
  ];
  const active = (id: string) => page === id || (page === "failure" && id === "failures") || (page === "skill" && id === "skills") || (page === "release" && id === "releases");
  const node = (item: { id: string; label: string; detail: string; href?: string }, index: number, total: number) => {
    const className = `${styles.lifecycleNode} ${active(item.id) ? styles.lifecycleNodeActive : ""}`;
    const content = <><span>{index + 1}</span><strong>{item.label}</strong><small>{item.detail}</small></>;
    return <div className={styles.lifecycleNodeWrap} key={item.id}>{item.href ? <a className={className} href={item.href}>{content}</a> : <article className={className}>{content}</article>}{index < total - 1 ? <i aria-hidden="true">→</i> : null}</div>;
  };
  return <section className={styles.observabilityCard} aria-label="Agent 全链路生命周期"><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Lifecycle map</p><h3>Agent 运行与持续改进闭环</h3></div><span>当前页面高亮 · 状态来自服务端</span></div><div className={styles.lifecycleLane}><div className={styles.lifecycleLaneTitle}><strong>在线请求链路</strong><span>一次请求如何从识别走到安全回复</span></div><div className={styles.lifecycleNodes}>{runtime.map((item, index) => node(item, index, runtime.length))}</div></div><div className={styles.lifecycleConnector} aria-hidden="true">↓ 结果反馈进入持续改进</div><div className={styles.lifecycleLane}><div className={styles.lifecycleLaneTitle}><strong>质量与学习链路</strong><span>自动化证据先沉淀，审批边界保持 fail-closed</span></div><div className={styles.lifecycleNodes}>{learning.map((item, index) => node(item, index, learning.length))}</div></div><p className={styles.flowNote}>页面之间通过不可变 ID、Run Trace、Case、失败簇、Skill 和 Release 证据下钻；没有后端关联时显示 N/A，不在浏览器端猜测关联。</p></section>;
}

function ReleaseLiveStatus({ id }: { id: string }) {
  const [item, setItem] = useState<Release | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let disposed = false;
    const load = async () => {
      try {
        const next = await getJson<Release>(`/internal/v1/releases/${encodeURIComponent(id)}`);
        if (!disposed) { setItem(next); setError(null); }
      } catch (reason) {
        if (!disposed) setError(reason);
      } finally {
        if (!disposed) setLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), RELEASE_STATUS_REFRESH_MS);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [id]);
  if (loading && !item) return <PageState kind="loading" title="正在同步发布状态…" />;
  if (error && !item) return errorState("发布状态加载失败", error);
  if (!item) return null;
  const comparisonKeys = [
    { key: "route", label: "Route" },
    { key: "response_policy", label: "Response Policy" },
    { key: "skill", label: "Skill" },
  ];
  const gateEntries = Object.entries(item.gates ?? {}).filter(([key]) => key !== "baseline");
  const latestEvents = (item.events ?? []).slice(0, 5);
  return <section className={styles.observabilityCard} aria-label="发布实时状态与审计">
    <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Live release monitor</p><h3>实时状态、Gate 与停止审计</h3></div><span className={styles.liveStatus}><i />每 15 秒刷新</span></div>
    <div className={styles.releaseMeta}><span>负责人：<strong>{item.owner_ref ?? "N/A"}</strong></span><span>最后更新：<strong>{showDate(item.updated_at)}</strong></span><span>观察窗口：<strong>{showDate(item.observation_ends_at)}</strong></span><span>当前状态：<strong>{showStatus(item.status)}</strong></span></div>
    <div className={styles.liveComparison}><div><strong>Current</strong><span>{item.current_version}</span></div><div className={styles.liveArrow}>→</div><div><strong>Candidate</strong><span>{item.candidate_version}</span></div><div className={styles.liveOutcome}><strong>{item.stop_reason ? "已停止" : "观测中"}</strong><span>{item.stop_reason ?? `${item.traffic_percent}% 候选流量`}</span></div></div>
    <div className={styles.comparisonTable}><div className={styles.comparisonHeader}><span>路由决策</span><strong>{item.current_version}</strong><strong>{item.candidate_version}</strong><b>变化</b></div>{comparisonKeys.map(({ key, label }) => <div className={styles.comparisonRow} key={key}><span>{label}</span><strong>{showValue(item.baseline?.[key])}</strong><strong>{showValue(item.candidate?.[key])}</strong><b>{showValueDelta(item.baseline?.[key], item.candidate?.[key])}</b></div>)}</div>
    <div className={styles.gateGrid}>{gateEntries.length === 0 ? <p className={styles.empty}>暂无结构化 Gate 指标；不将缺失值视为通过。</p> : gateEntries.map(([key, value]) => <div className={styles.gateItem} key={key}><span>{gateLabel[key] ?? key}</span><strong>{typeof value === "boolean" ? (value ? "通过" : "阻断") : showValue(value)}</strong></div>)}</div>
    {item.stop_reason ? <p className={styles.flowWarningBox}>停止原因：{item.stop_reason} · 回滚版本：{item.rollback_version ?? "N/A"}</p> : null}
    <div className={styles.releaseEvents}><strong>最近审计事件</strong>{latestEvents.length === 0 ? <span>暂无审计事件</span> : latestEvents.map((event) => <div key={event.event_id}><span>{event.event_type}</span><small>{event.actor_ref ?? "N/A"} · {showDate(event.created_at)}</small><b>{String(event.payload?.reason ?? event.payload?.stage ?? "状态已记录")}</b></div>)}</div>
    {error ? <p className={styles.flowNote}>本次刷新失败，仍展示上次成功快照：{error instanceof Error ? error.message : "接口请求失败"}</p> : null}
  </section>;
}

function FailureList() {
  const [items, setItems] = useState<Failure[]>([]);
  const [summary, setSummary] = useState<FailureSummary | null>(null);
  const [windowDays, setWindowDays] = useState(30);
  const [error, setError] = useState<unknown>(null);
  const [summaryError, setSummaryError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setLoading(true);
    setError(null); setSummaryError(null);
    Promise.allSettled([
      getJson<{ items: Failure[] }>("/internal/v1/failures"),
      getJson<FailureSummary>(`/internal/v1/failures/summary?window_days=${windowDays}`),
    ])
      .then(([failureResult, summaryResult]) => {
        if (failureResult.status === "fulfilled") setItems(failureResult.value.items);
        else setError(failureResult.reason);
        if (summaryResult.status === "fulfilled") setSummary(summaryResult.value);
        else setSummaryError(summaryResult.reason);
      })
      .finally(() => setLoading(false));
  }, [windowDays]);
  const pendingReviews = items.filter((item) => !item.attribution || !item.attribution.review_status || item.attribution.review_status === "pending").length;
  if (loading) return <PageState kind="loading" title="正在读取失败样本…" />;
  if (error && items.length === 0) return errorState("失败样本加载失败", error);
  const topClusters = summary?.top_clusters ?? [];
  const categories = summary?.taxonomy ?? [];
  const maxTrend = Math.max(1, ...(summary?.trend.map((point) => point.case_count) ?? [1]));
  return <>
    {error ? <PageState kind="partial" title="失败样本下钻不完整" detail={error instanceof Error ? error.message : "失败样本接口不可用"} /> : null}
    {summaryError ? <PageState kind="partial" title="失败聚合不完整" detail={summaryError instanceof Error ? summaryError.message : "失败聚合接口不可用"} /> : null}
    <section className={styles.toolbar}><div><strong>失败归因聚合</strong><span>服务端按租户聚合，不使用浏览器当前样本估算趋势</span></div><label>时间范围<select value={windowDays} onChange={(event) => setWindowDays(Number(event.target.value))}><option value={7}>最近 7 天</option><option value={30}>最近 30 天</option><option value={90}>最近 90 天</option></select></label></section>
    <section className={styles.metricGrid}>
      <article><span>窗口内失败</span><strong>{summary?.trend.reduce((total, point) => total + point.case_count, 0) ?? "N/A"}</strong><small>服务端聚合</small></article>
      <article><span>P0 / P1</span><strong>{summary?.trend.reduce((total, point) => total + point.critical_count, 0) ?? "N/A"}</strong><small>需要优先处置</small></article>
      <article><span>来源簇门槛</span><strong>5</strong><small>独立证据后才生成 Skill</small></article>
      <article><span>待归因复核</span><strong>{pendingReviews}</strong><small>当前可见样本 · 自动结果不是人工结论</small></article>
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Failure distribution</p><h3>失败簇、taxonomy 与趋势</h3></div><span>窗口 {summary?.window_days ?? "N/A"} 天</span></div>
      <div className={styles.scoreGrid}>{topClusters.length === 0 ? <p className={styles.empty}>窗口内暂无可聚合失败样本。</p> : topClusters.map((cluster) => <article key={cluster.cluster_key}><div><span>Cluster</span><strong>{cluster.case_count}</strong></div><small>{cluster.cluster_key} · 最大来源 {cluster.max_source_count ?? "N/A"}</small></article>)}{categories.map((category) => <article key={category.category}><div><span>{category.category}</span><strong>{category.case_count}</strong></div><small>服务端 taxonomy 聚合</small></article>)}</div>
      {summary?.trend.length ? <div className={styles.trendBars} aria-label="失败趋势">{summary.trend.map((point) => <div key={point.bucket}><i><b style={{ height: `${Math.max(4, point.case_count / maxTrend * 100)}%` }} /></i><strong>{point.case_count}</strong><small>{new Date(point.bucket).toLocaleDateString()}</small></div>)}</div> : <p className={styles.empty}>暂无趋势数据。</p>}
    </section>
    <section className={styles.observabilityCard}><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Failure cases</p><h3>失败样本池</h3></div><span>{items.length} 条当前下钻样本</span></div>{items.length === 0 ? <p className={styles.empty}>暂无真实失败样本。失败 Run 或用户点踩后会在这里出现。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><thead><tr><th>信号</th><th>严重度</th><th>摘要</th><th>来源数</th><th>状态</th><th>关联 Run</th><th>评测 Case</th><th>更新时间</th></tr></thead><tbody>{items.map((item) => <tr key={item.failure_id}><td><a href={"/failures/" + item.failure_id}>{item.signal}</a></td><td>{item.severity}</td><td>{item.summary_redacted}</td><td>{item.source_count}</td><td>{showStatus(item.status)}</td><td>{item.run_id ? <a href={`/runs/${encodeURIComponent(item.run_id)}`}>{item.run_id.slice(0, 8)}…</a> : "N/A"}</td><td>{item.eval_run_id && item.case_id ? <a href={`/evals/${encodeURIComponent(item.eval_run_id)}?case_id=${encodeURIComponent(item.case_id)}`}>{item.case_id}</a> : "N/A"}</td><td>{showDate(item.updated_at)}</td></tr>)}</tbody></table></div>}</section>
    <SkillCandidateShortcut items={items} />
  </>;
}

function SkillCandidateShortcut({ items }: { items: Failure[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Record<string, string>>({});
  const create = async (failure: Failure) => {
    setBusy(failure.failure_id); setError(null);
    try {
      const result = await getJson<{ skill_id: string }>(`/internal/v1/failures/${encodeURIComponent(failure.failure_id)}/skill`, {
        method: "POST",
        body: JSON.stringify({ idempotency_key: `web-skill-${failure.failure_id}` }),
      });
      setCreated((current) => ({ ...current, [failure.failure_id]: result.skill_id }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "候选 Skill 创建失败");
    } finally { setBusy(null); }
  };
  if (items.length === 0) return null;
  return <section className={styles.observabilityCard} aria-label="失败簇到 Skill 候选"><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Skill candidate bridge</p><h3>从失败簇生成候选</h3></div><span>仅脱敏 taxonomy / cluster</span></div>{error ? <p className={styles.error} role="alert">{error}</p> : null}<div className={styles.tableScroller}><table className={styles.dataTable}><thead><tr><th>Cluster</th><th>来源数</th><th>门槛</th><th>结果</th></tr></thead><tbody>{items.map((failure) => <tr key={failure.failure_id}><td><a href={`/failures/${failure.failure_id}`}>{failure.cluster_key}</a></td><td>{failure.source_count}</td><td>{failure.source_count >= 5 ? "已达到 5 个独立来源" : "未达到生成门槛"}</td><td>{created[failure.failure_id] ? <a href={`/skills/${created[failure.failure_id]}`}>查看候选 Skill</a> : failure.source_count >= 5 ? <button type="button" onClick={() => void create(failure)} disabled={busy !== null}>{busy === failure.failure_id ? "生成中…" : "生成待审候选"}</button> : "—"}</td></tr>)}</tbody></table></div><p className={styles.flowNote}>自动生成只会创建 `PENDING_REVIEW` 候选；不读取或展示原始失败文本，也不会自动激活。</p></section>;
}

function FailureDetail({ id }: { id: string }) {
  const [item, setItem] = useState<Failure | null>(null); const [error, setError] = useState<unknown>(null); const [busy, setBusy] = useState(false); const [reviewBusy, setReviewBusy] = useState(false); const [reviewOutcome, setReviewOutcome] = useState<"verified_success" | "verified_failure">("verified_failure"); const [reviewCategory, setReviewCategory] = useState(""); const [reviewNote, setReviewNote] = useState("");
  useEffect(() => { void getJson<Failure>("/internal/v1/failures/" + encodeURIComponent(id)).then(setItem).catch(setError); }, [id]);
  if (error) return errorState("失败证据加载失败", error);
  if (!item) return <PageState kind="loading" title="正在读取失败证据…" />;
  const reanalyze = async () => { setBusy(true); try { setItem(await getJson<Failure>("/internal/v1/failures/" + item.failure_id + "/reanalyze", { method: "POST", body: JSON.stringify({ idempotency_key: "web-reanalyze-" + item.failure_id }) })); } catch (reason) { setError(reason); } finally { setBusy(false); } };
  const attributionReady = Boolean(item.attribution);
  const failureSteps = [
    { label: "失败信号", detail: `${item.source_count} 个来源`, state: "flowPassed" },
    { label: "相似聚类", detail: item.cluster_key, state: item.source_count >= 5 ? "flowPassed" : "flowBlocked" },
    { label: "确定性 / LLM 归因", detail: attributionReady ? "已有结构化建议" : "待分析", state: attributionReady ? "flowPassed" : "flowActive" },
    { label: "人工复核", detail: "自动结果不能替代真人结论", state: ["reviewed", "verified", "approved"].includes(item.status.toLowerCase()) ? "flowPassed" : "flowBlocked" },
  ];
  const review = async () => { setReviewBusy(true); try { setItem(await getJson<Failure>("/internal/v1/failures/" + item.failure_id + "/review", { method: "POST", body: JSON.stringify({ outcome: reviewOutcome, category: reviewCategory || null, review_note: reviewNote, idempotency_key: "web-review-" + item.failure_id + "-" + reviewOutcome }) })); setReviewNote(""); } catch (reason) { setError(reason); } finally { setReviewBusy(false); } };
  const reviewPending = !item.attribution || !item.attribution.review_status || item.attribution.review_status === "pending";
  return <section className={styles.observabilityCard}><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Failure evidence</p><h3>{item.signal} · {item.severity}</h3></div><span>{showStatus(item.status)}</span></div><div className={styles.approvalFlow} aria-label="失败学习链路">{failureSteps.map((step, index) => <div className={styles.approvalFlowFragment} key={step.label}><article className={styles[step.state]}><span>{index + 1}</span><strong>{step.label}</strong><small>{step.detail}</small></article>{index < failureSteps.length - 1 ? <i aria-hidden="true">→</i> : null}</div>)}</div><dl className={styles.decisionFacts}><div><dt>脱敏摘要</dt><dd>{item.summary_redacted}</dd></div><div><dt>Cluster</dt><dd>{item.cluster_key}</dd></div><div><dt>来源数量</dt><dd>{item.source_count}</dd></div><div><dt>Run</dt><dd>{item.run_id ? <a href={`/runs/${encodeURIComponent(item.run_id)}`}>{item.run_id}</a> : "N/A"}</dd></div><div><dt>评测 Case</dt><dd>{item.eval_run_id && item.case_id ? <a href={`/evals/${encodeURIComponent(item.eval_run_id)}?case_id=${encodeURIComponent(item.case_id)}`}>{item.case_id}</a> : "N/A"}</dd></div><div><dt>Trace event 引用</dt><dd>{item.trace_refs?.length ? <div className={styles.tagList}>{item.trace_refs.map((ref) => <code key={ref}>{ref}</code>)}</div> : "N/A"}</dd></div></dl><div className={styles.reviewDetails}><strong>自动归因结果</strong>{item.attribution ? Object.entries(item.attribution).filter(([key]) => !["review_note_redacted"].includes(key)).map(([key, value]) => <div key={key}><span>{key}</span><strong>{String(value ?? "N/A")}</strong></div>) : <p className={styles.empty}>尚无归因记录。自动化归因完成后仍需人工复核。</p>}</div>{reviewPending ? <section className={styles.reviewPanel} aria-label="失败归因人工复核"><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Human review</p><h3>确认归因结论</h3></div><span>需管理员确认</span></div><div className={styles.reviewFormGrid}><label>结论<select value={reviewOutcome} onChange={(event) => setReviewOutcome(event.target.value as "verified_success" | "verified_failure")}><option value="verified_failure">确认失败</option><option value="verified_success">确认成功</option></select></label><label>归因类别<select value={reviewCategory} onChange={(event) => setReviewCategory(event.target.value)}><option value="">沿用自动归因</option><option value="intent_error">意图错误</option><option value="policy_error">策略错误</option><option value="tool_error">工具错误</option><option value="retrieval_error">检索错误</option><option value="safety_error">安全错误</option><option value="model_error">模型错误</option><option value="response_error">回复错误</option><option value="unknown">未知</option></select></label></div><textarea aria-label="归因复核说明" value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="填写可复用的复核事实，不要粘贴原始用户信息" rows={3} disabled={reviewBusy} /><button type="button" onClick={() => void review()} disabled={reviewBusy || !reviewNote.trim()}>{reviewBusy ? "提交中…" : "提交人工结论"}</button></section> : <p className={styles.muted}>人工结论：{item.attribution?.reviewed_category ?? "沿用自动归因"} · {item.attribution?.reviewed_by ?? "已记录"}</p>}<button type="button" onClick={() => void reanalyze()} disabled={busy}>{busy ? "分析中…" : "重新运行确定性归因"}</button><div className={styles.flowLinks}><a href="/failures">返回失败归因池 ↗</a><a href="/skills">查看 Skill Registry ↗</a></div></section>;
}

function SkillList() {
  const [items, setItems] = useState<Skill[]>([]); const [control, setControl] = useState<SkillControl | null>(null); const [canMutate, setCanMutate] = useState(false); const [error, setError] = useState<unknown>(null); const [loading, setLoading] = useState(true); const [controlBusy, setControlBusy] = useState(false);
  const reload = () => { setLoading(true); setError(null); void Promise.all([getJson<{ items: Skill[] }>("/internal/v1/skills"), getJson<SkillControl>("/internal/v1/skills/kill-switch")]).then(([data, skillControl]) => { setItems(data.items); setControl(skillControl); setCanMutate(skillControl.can_mutate); }).catch((reason: unknown) => { setError(reason); void getJson<{ items: Skill[] }>("/internal/v1/skills").then((data) => setItems(data.items)).catch(() => undefined); }).finally(() => setLoading(false)); };
  useEffect(reload, []);
  const counts = useMemo(() => Object.fromEntries(Object.keys(labels).map((key) => [key, items.filter((item) => item.status === key).length])), [items]);
  const approve = async (id: string) => {
    if (!window.confirm("确认将该 Skill 送入人工批准流程？自动评测通过不等于上线授权。")) return;
    const reason = window.prompt("填写审批原因（必填）", "已复核质量、安全、成本和时延门禁");
    if (!reason?.trim()) { setError("审批原因不能为空"); return; }
    try {
      await getJson("/internal/v1/skills/" + id + "/approve", {
        method: "POST",
        body: JSON.stringify({
          reason: reason.trim(),
          confirmation: `CONFIRM APPROVE ${id}`,
          idempotency_key: "web-approve-" + id,
        }),
      });
      reload();
    } catch (reasonError) { setError(reasonError instanceof Error ? reasonError.message : "审批失败"); }
  };
  const toggleKillSwitch = async () => {
    if (!control || !canMutate) return;
    const enabled = !control.matching_enabled;
    if (!window.confirm(`${enabled ? "恢复" : "暂停"}当前租户的 Skill 命中？历史版本和命中记录不会删除。`)) return;
    const reason = window.prompt("填写操作原因（必填）", enabled ? "恢复 Skill 匹配" : "故障处置，暂停 Skill 匹配");
    if (!reason?.trim()) { setError("操作原因不能为空"); return; }
    setControlBusy(true); setError(null);
    try {
      const result = await getJson<SkillControl>("/internal/v1/skills/kill-switch", {
        method: "POST",
        body: JSON.stringify({
          enabled,
          reason: reason.trim(),
          confirmation: "CONFIRM SKILL_KILL_SWITCH demo-tenant",
          idempotency_key: `web-skill-kill-switch-${crypto.randomUUID()}`,
        }),
      });
      setControl(result);
    } catch (reasonError) { setError(reasonError instanceof Error ? reasonError.message : "Skill 开关更新失败"); }
    finally { setControlBusy(false); }
  };
  if (loading) return <PageState kind="loading" title="正在读取 Skill Registry…" />;
  if (error && items.length === 0) return errorState("Skill Registry 加载失败", error);
  return <><section className={styles.metricGrid}>{["CANDIDATE", "PENDING_REVIEW", "APPROVED", "CANARY", "ACTIVE", "REJECTED", "EXPIRED", "ROLLED_BACK"].map((key) => <article key={key}><span>{showStatus(key)}</span><strong>{counts[key] ?? 0}</strong><small>Skill 数量</small></article>)}</section><section className={styles.observabilityCard} aria-label="Skill kill switch"><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Runtime safety control</p><h3>Skill 命中开关</h3></div><span className={control ? (control.matching_enabled ? styles.statusBadge : styles.badgeDanger) : styles.pageStateBadge}>{control ? (control.matching_enabled ? "已启用" : "已暂停") : "N/A"}</span></div><p className={styles.flowNote}>暂停只阻止新请求命中 Skill，不删除历史版本和匹配记录；运行时每次检索前读取该租户状态，控制面异常时自动回退普通路由。</p>{canMutate ? <button type="button" className={styles.secondaryButton} onClick={() => void toggleKillSwitch()} disabled={!control || controlBusy}>{controlBusy ? "更新中…" : control?.matching_enabled ? "暂停 Skill 命中" : "恢复 Skill 命中"}</button> : <p className={styles.empty}>当前身份不可操作；仅审批角色可以查看或修改开关。</p>}</section><section className={styles.observabilityCard}><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Registry</p><h3>候选与审批队列</h3></div><span>自动评测 ≠ 真人审批</span></div><p className={styles.flowNote}>变更按钮仅对审批角色开放；每次操作还需要二次确认、原因、幂等键和服务端确认短语。普通运营角色保持只读。</p>{error ? <PageState kind="partial" title="Skill 控制面部分不可用" detail={error instanceof Error ? error.message : "部分接口不可用"} /> : null}{items.length === 0 ? <p className={styles.empty}>暂无真实 Skill。达到 5 个不同来源的相似失败、且通过安全与离线门禁后才会生成候选。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><thead><tr><th>Skill</th><th>状态</th><th>来源数</th><th>离线/安全</th><th>Paired eval</th><th>TTL</th><th>操作</th></tr></thead><tbody>{items.map((item) => { const evaluationReady = item.evaluation_gate_pass === true && item.evaluation_safety_result === "pass" && item.evaluation_judge_disagreement_count === 0; const canApprove = canMutate && item.status === "PENDING_REVIEW" && item.offline_gate_pass && item.safety_gate_pass && evaluationReady; return <tr key={item.skill_id}><td><a href={"/skills/" + item.skill_id}>{item.scope_value}</a><small>{item.cluster_key}</small></td><td>{showStatus(item.status)}</td><td>{item.source_count}</td><td>{item.offline_gate_pass && item.safety_gate_pass ? "通过" : "未通过"}</td><td>{item.evaluation_gate_pass === undefined ? "未评测" : evaluationReady ? "通过" : `阻断（分歧 ${item.evaluation_judge_disagreement_count ?? 0}）`}</td><td>{showDate(item.review_deadline)}</td><td>{item.status === "PENDING_REVIEW" && canMutate ? <button type="button" onClick={() => void approve(item.skill_id)} disabled={!canApprove} title={!canApprove ? "需先通过 paired evaluation、安全和一致性门禁" : undefined}>人工批准</button> : "—"}</td></tr>; })}</tbody></table></div>}</section></>;
}

function SkillEvaluationEvidence({ evaluations }: { evaluations?: SkillEvaluation[] }) {
  if (!evaluations?.length) return <section className={styles.reviewDetails}><strong>Paired before / after 评测</strong><p className={styles.empty}>暂无已持久化的聚合评测结果。自动评测未完成或结果不完整时显示 N/A。</p></section>;
  const latest = evaluations[0];
  const before = latest.before ?? {};
  const after = latest.after ?? {};
  const gateBlocked = !latest.gate_pass || latest.safety_result !== "pass" || latest.judge_disagreement_count > 0;
  return <section className={styles.reviewDetails}>
    <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Paired evaluation</p><h3>候选 Skill 前后对比</h3></div><span className={gateBlocked ? styles.badgeDanger : styles.statusBadge}>{gateBlocked ? "Gate 阻断" : "Gate 通过"}</span></div>
    <div className={styles.scoreGrid}>
      <article><div><span>Quality</span><strong>{showDelta(before.quality, after.quality)}</strong></div><small>before → after</small></article>
      <article><div><span>Safety pass rate</span><strong>{showDelta(before.safety_pass_rate, after.safety_pass_rate)}</strong></div><small>before → after</small></article>
      <article><div><span>P95 latency</span><strong>{showDelta(before.p95_latency_ms, after.p95_latency_ms, " ms")}</strong></div><small>before → after</small></article>
      <article><div><span>P95 cost</span><strong>{showDelta(before.p95_cost_microusd, after.p95_cost_microusd, " μUSD")}</strong></div><small>before → after</small></article>
      <article><div><span>Handoff rate</span><strong>{showDelta(before.handoff_rate, after.handoff_rate)}</strong></div><small>before → after</small></article>
      <article><div><span>Judge disagreement</span><strong>{latest.judge_disagreement_count}</strong></div><small>{latest.safety_result === "pass" ? "安全评测通过" : "安全评测未通过"}</small></article>
    </div>
    <div className={styles.tableScroller}><table className={styles.dataTable}><thead><tr><th>数据集</th><th>安全</th><th>成本变化</th><th>时延变化</th><th>Gate</th><th>时间</th></tr></thead><tbody>{evaluations.map((evaluation) => <tr key={evaluation.evaluation_id}><td>{evaluation.dataset_hash}</td><td>{evaluation.safety_result}</td><td>{showMetric(evaluation.cost_delta_microusd, " μUSD")}</td><td>{showMetric(evaluation.latency_delta_ms, " ms")}</td><td>{evaluation.gate_pass && evaluation.judge_disagreement_count === 0 ? "通过" : "阻断"}</td><td>{showDate(evaluation.created_at)}</td></tr>)}</tbody></table></div>
    <p className={styles.muted}>{gateBlocked ? "未满足安全、Judge 一致性或门禁条件，不能推进 Skill 生命周期。" : "聚合指标可用于推进门禁；原始 Prompt、回复、工具参数和思维链不会持久化或展示。"}</p>
  </section>;
}

function SkillDetail({ id }: { id: string }) { const [item, setItem] = useState<Skill | null>(null); const [error, setError] = useState<unknown>(null); useEffect(() => { void getJson<Skill>("/internal/v1/skills/" + encodeURIComponent(id)).then(setItem).catch(setError); }, [id]); if (error) return errorState("Skill 详情加载失败", error); if (!item) return <PageState kind="loading" title="正在读取 Skill…" />; const pending = item.status === "CANDIDATE" || item.status === "PENDING_REVIEW"; const definition = item.versions?.[0]?.definition ?? {}; return <section className={styles.observabilityCard}><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Skill evidence</p><h3>{item.scope_value}</h3></div><span>{showStatus(item.status)}</span></div><div className={styles.reviewPanel + " " + (pending ? styles.flowBlocked : styles.flowPassed)}><strong>{pending ? "自动化评测已停止在审批边界" : "已通过审批边界"}</strong><small>{pending ? "没有真人审批时保持 PENDING_REVIEW，不匹配线上 Active，也不会自动 Canary。" : "后续仍需按 Shadow → Canary 门禁推进。"}</small></div><dl className={styles.decisionFacts}><div><dt>Scope</dt><dd>{item.scope_type} / {item.scope_value}</dd></div><div><dt>来源簇</dt><dd>{item.cluster_key}</dd></div><div><dt>独立证据数</dt><dd>{item.source_count}</dd></div><div><dt>离线 Gate</dt><dd>{item.offline_gate_pass ? "通过" : "未通过"}</dd></div><div><dt>安全 Gate</dt><dd>{item.safety_gate_pass ? "通过" : "未通过"}</dd></div><div><dt>审批截止</dt><dd>{showDate(item.review_deadline)}</dd></div><div><dt>触发摘要</dt><dd>{JSON.stringify(item.trigger)}</dd></div><div><dt>策略摘要</dt><dd>{JSON.stringify(item.strategy)}</dd></div><div><dt>正例</dt><dd>{JSON.stringify(definition.positive_examples ?? "N/A")}</dd></div><div><dt>反例</dt><dd>{JSON.stringify(definition.negative_examples ?? "N/A")}</dd></div><div><dt>允许决策</dt><dd>{JSON.stringify(definition.allowed_decisions ?? "N/A")}</dd></div><div><dt>禁止工具</dt><dd>{JSON.stringify(definition.forbidden_tools ?? "N/A")}</dd></div><div><dt>TTL</dt><dd>{definition.ttl_seconds ? `${String(definition.ttl_seconds)} 秒` : "N/A"}</dd></div><div><dt>来源摘要</dt><dd>{item.provenance ? JSON.stringify(item.provenance) : "N/A"}</dd></div></dl><section className={styles.reviewDetails}><strong>版本不可变与生命周期</strong>{item.versions?.length ? item.versions.map((version) => <div key={version.skill_version_id}><span>v{version.version_no} · {showStatus(version.status)}</span><strong>{version.definition_hash} · 到期 {showDate(version.expires_at)}</strong></div>) : <p className={styles.empty}>暂无版本记录。</p>}</section><SkillEvaluationEvidence evaluations={item.evaluations} /><p className={styles.muted}>页面不展示可绕过规则的内部提示、Prompt 或原始用户文本。</p></section>; }

function ReleaseList() {
  const [items, setItems] = useState<Release[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let disposed = false;
    void getJson<{ items: Release[] }>("/internal/v1/releases")
      .then((data) => { if (!disposed) setItems(data.items); })
      .catch((reason: unknown) => { if (!disposed) setError(reason); })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, []);

  if (loading) return <PageState kind="loading" title="正在读取发布控制面…" />;
  if (error) return errorState("发布列表加载失败", error);
  return <>
    <section className={styles.metricGrid}>
      <article><span>发布记录</span><strong>{items.length}</strong><small>当前租户</small></article>
      <article><span>Active</span><strong>{items.filter((item) => item.status === "ACTIVE").length}</strong><small>渐进发布中</small></article>
      <article><span>停止</span><strong>{items.filter((item) => item.status === "STOPPED").length}</strong><small>自动或人工停止</small></article>
      <article><span>当前流量</span><strong>{items[0]?.traffic_percent ?? "N/A"}{items[0] ? "%" : ""}</strong><small>最新发布</small></article>
    </section>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Progressive delivery</p><h3>发布队列</h3></div><span>异常自动停止</span></div>
      {items.length === 0
        ? <PageState kind="empty" title="暂无真实发布记录" detail="Skill 必须先通过人工审批与离线门禁。" />
        : <div className={styles.tableScroller}><table className={styles.dataTable}><thead><tr><th>版本</th><th>阶段</th><th>流量</th><th>状态</th><th>观察窗口</th><th>停止原因</th></tr></thead><tbody>{items.map((item) => <tr key={item.release_id}><td><a href={"/releases/" + encodeURIComponent(item.release_id)}>{item.current_version} → {item.candidate_version}</a></td><td>{showStatus(item.stage)}</td><td>{item.traffic_percent}%</td><td>{showStatus(item.status)}</td><td>{showDate(item.observation_ends_at)}</td><td>{item.stop_reason ?? "—"}</td></tr>)}</tbody></table></div>}
    </section>
  </>;
}

function ReleaseDetail({ id }: { id: string }) {
  const [item, setItem] = useState<Release | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let disposed = false;
    void getJson<Release>("/internal/v1/releases/" + encodeURIComponent(id))
      .then((next) => { if (!disposed) setItem(next); })
      .catch((reason: unknown) => { if (!disposed) setError(reason); });
    return () => { disposed = true; };
  }, [id]);

  if (error) return errorState("发布详情加载失败", error);
  if (!item) return <PageState kind="loading" title="正在读取发布证据…" />;

  const stages = ["SHADOW", "CANARY_5", "CANARY_25", "CANARY_50", "FULL"];
  const currentIndex = stages.indexOf(item.stage);
  const knownStage = currentIndex >= 0;
  const stageClass = (stage: string, index: number) =>
    index < currentIndex
      ? styles.flowPassed
      : index === currentIndex && item.status !== "STOPPED" && item.status !== "ROLLED_BACK"
        ? (stage === "FULL" ? styles.flowPassed : styles.flowActive)
        : index === currentIndex ? styles.flowBlocked : styles.flowPendingBox;
  const comparisons = [
    { key: "quality", label: "质量", suffix: "" },
    { key: "safety_pass_rate", label: "安全通过率", suffix: "" },
    { key: "p95_e2e_ms", label: "P95 时延", suffix: " ms" },
    { key: "p95_cost_microusd", label: "P95 成本", suffix: " μUSD" },
    { key: "handoff_rate", label: "人工接管率", suffix: "" },
  ];
  const hasComparison = comparisons.some(({ key }) => typeof item.baseline?.[key] === "number" || typeof item.candidate?.[key] === "number");

  return <section className={styles.observabilityCard}>
    <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Release evidence</p><h3>{item.current_version} → {item.candidate_version}</h3></div><StatusTag value={item.status} label={showStatus(item.status)} /></div>
    {!knownStage ? <PageState kind="partial" title="发布阶段未知" detail={`服务端返回了未识别阶段“${item.stage}”，不会推断为可扩流。`} /> : null}
    <div className={styles.approvalFlow} aria-label="渐进发布阶段">{stages.map((stage, index) => <div className={styles.approvalFlowFragment} key={stage}><article className={stageClass(stage, index)}><span>{index < currentIndex ? "✓" : index + 1}</span><strong>{showStatus(stage)}</strong><small>{index < currentIndex ? "已完成" : item.stage === stage ? item.traffic_percent + "% 流量" : "待推进"}</small></article>{index < stages.length - 1 ? <i aria-hidden="true">→</i> : null}</div>)}</div>
    <div className={styles.releaseTraffic} aria-label="候选版本流量进度"><div><span>候选版本当前流量</span><strong>{item.traffic_percent}%</strong></div><div className={styles.releaseTrafficTrack}><i style={{ width: `${Math.max(0, Math.min(100, item.traffic_percent))}%` }} /></div><small>Shadow 不改变用户可见结果；高风险和写操作不会自动扩流。</small></div>
    <section className={styles.observabilityCard} aria-label="Current Candidate 指标对比"><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Current / Candidate delta</p><h3>质量、安全、时延、成本和人工接管对比</h3></div><span>{hasComparison ? "服务端聚合" : "N/A"}</span></div>{hasComparison ? <div className={styles.scoreGrid}>{comparisons.map(({ key, label, suffix }) => <article key={key}><div><span>{label}</span><strong>{showDelta(item.baseline?.[key] as number | null | undefined, item.candidate?.[key] as number | null | undefined, suffix)}</strong></div><small>Current → Candidate · 缺失值不推断</small></article>)}</div> : <p className={styles.empty}>暂无 Current/Candidate 聚合指标；不把未提供的线上数据显示为 0。</p>}</section>
    <dl className={styles.decisionFacts}><div><dt>观察开始</dt><dd>{showDate(item.observation_started_at)}</dd></div><div><dt>观察结束</dt><dd>{showDate(item.observation_ends_at)}</dd></div><div><dt>Gate</dt><dd>{JSON.stringify(item.gates)}</dd></div><div><dt>停止原因</dt><dd>{item.stop_reason ?? "N/A"}</dd></div></dl>
    <section className={styles.reviewDetails}><strong>实际 assignment（仅展示脱敏 Run）</strong>{item.assignments?.length ? <div className={styles.tableScroller}><table className={styles.dataTable}><thead><tr><th>Run</th><th>模式</th><th>版本</th><th>桶位/流量</th><th>风险</th><th>原因</th></tr></thead><tbody>{item.assignments.map((assignment) => <tr key={assignment.assignment_id}><td><a href={`/runs/${encodeURIComponent(assignment.run_id)}`}>{assignment.run_id.slice(0, 8)}…</a></td><td>{assignment.mode}</td><td>{assignment.selected_version}</td><td>{assignment.bucket} / {assignment.traffic_percent}%</td><td>{assignment.risk_level} · {assignment.risk_hint}</td><td>{assignment.reason}</td></tr>)}</tbody></table></div> : <p className={styles.empty}>尚无 Run assignment；当前仅有发布控制面记录。</p>}</section>
  </section>;
}

export function EvolutionLifecycle({ page }: { page: Page }) { const selected = copy[page]; const id = window.location.pathname.split("/").pop() ?? ""; return <div className={styles.insightPage}><section className={styles.runHero}><div><p className={styles.eyebrow}>{selected.eyebrow}</p><h3>{selected.title}</h3><p>{selected.description}</p></div><span className={styles.statusBadge}>结构化控制面</span></section><ProcessFlow page={page} />{page === "failures" ? <FailureList /> : page === "failure" ? <FailureDetail id={id} /> : page === "skills" ? <SkillList /> : page === "skill" ? <SkillDetail id={id} /> : page === "releases" ? <ReleaseList /> : <><ReleaseLiveStatus id={id} /><ReleaseDetail id={id} /></>}</div>; }
