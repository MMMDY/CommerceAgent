import { useEffect, useState } from "react";

import styles from "../styles/App.module.css";
import { api, ApiError } from "../api/client";
import { PageState } from "./PageState";
import { StatusTag } from "./StatusTag";
import { MultiTurnExplorer } from "./MultiTurnExplorer";

type EvalSummary = { eval_run_id: string; status: string; selected_cases: number; completed_cases: number; passed_cases: number; failed_cases: number; judge: string; mode: string; repetitions: number; runtime?: string | null; dataset_id?: string | null; dataset_version?: string | null; dataset_hash?: string | null; manifest_hash?: string | null };
type EvalCase = { case_id: string; track: string; hard_pass: boolean; judge_pass: boolean | null; final_pass: boolean | null; judge_score: number | null; hard_fail_reasons: string[]; judge_error: string | null; dimensions?: Record<string, boolean>; judge_dimensions?: Record<string, number> | null };
type EvalCaseDetail = {
  case_id: string | null;
  track: string;
  attempt_no: number;
  hard: { passed: boolean | null; fail_reasons: string[] };
  judge: { passed: boolean | null; score: number | null; dimensions: Record<string, number>; error: string | null; summary: string | null; evidence: string[] };
  final_pass: boolean | null;
  runtime_error: string | null;
  trace: { run_id?: string | null; route: string | null; intent: string | null; next_action: string | null; tools_called: string[]; evidence_ids: string[]; status: string; response_present: boolean | null };
  flow: { id: string; label: string; status: string; detail: string }[];
  failure_ids?: string[];
};
type Metric = { mean: number; count: number };
type HardMetric = { passed: number; total: number; rate: number | null };
type HardDimensionStats = Record<string, Record<string, HardMetric>>;
type MultiTurnMetric = { mean: number | null; count: number };
type Distribution = { mean: number | null; count: number; p50: number | null; p95: number | null; p99: number | null };
type Track = { selected: number; attempts?: number; hard_pass: number; judge_pass: number; final_pass: number };
type ReviewedSafetyStats = {
  status: string;
  reviewed_case_count: number;
  low_risk_case_count: number;
  high_risk_case_count: number;
  missing_label_count: number;
  false_negative_count: number | null;
  false_rejection_count: number | null;
  false_negative_rate: number | null;
  false_rejection_rate: number | null;
  gate_pass: boolean | null;
};
type EvalReport = EvalSummary & {
  schema_version?: string;
  first_pass_rate?: number;
  all_repetitions_pass_rate?: number;
  release_gate?: boolean;
  provisional?: boolean;
  self_judged?: boolean;
  dataset_hash?: string | null;
  runtime_hash?: string | null;
  tracks?: Record<string, Track>;
  judge_dimension_stats?: Record<string, Record<string, Metric>>;
  judge_score_stats?: Record<string, Metric>;
  runtime?: string;
  dataset_id?: string;
  dataset_version?: string;
  manifest_hash?: string | null;
  synthesis_cost_microusd?: number | null;
  persistence?: string;
  human_approval?: { required?: boolean; status?: string; source?: string };
  performance_stats?: Record<string, Record<string, Distribution>>;
  hard_dimension_stats?: HardDimensionStats;
  failure_reason_stats?: Record<string, number>;
  multiturn_stats?: {
    scenario_count: number;
    dialogue_count: number;
    evaluation_noise_count: number;
    intent_coverage?: MultiTurnMetric;
    agenda_progress?: MultiTurnMetric;
    exposed_intent_accuracy?: MultiTurnMetric;
    task_success_rate?: MultiTurnMetric;
    status?: string;
  };
  catalog_stats?: {
    selection?: Record<string, unknown>;
    response?: Record<string, unknown>;
    safety?: Record<string, unknown>;
  };
  rag_stats?: {
    status?: string;
    case_count?: number;
    recall_at_k?: Record<string, unknown>;
    precision_at_k?: Record<string, unknown>;
    grounding_rate?: Record<string, unknown>;
  };
  safety_stats?: { high_risk_cases: number; p0_failure_count: number; safe_next_step_failure_count: number; safe_next_step_critical_pass: boolean; safe_next_step_pass_rate: number; handoff_count?: number; reviewed?: ReviewedSafetyStats };
  results?: EvalCase[];
};
type DashboardFunnelStage = { id: string; label: string; count: number | null; available: boolean };
type EvalDashboardDto = {
  schema_version: string;
  dto: string;
  status: string;
  runtime: string;
  mode: string;
  judge: string;
  self_judged: boolean | null;
  provisional: boolean | null;
  counts: { selected: number | null; completed: number | null; passed: number | null; failed: number | null; attempts: number | null; repetitions: number };
  rates: { first_pass: number | null; all_repetitions_pass: number | null };
  gate: { release_gate: boolean | null; hard_gate: string; status: string; reasons: string[] };
  human_approval: { required: boolean; status: string; source: string };
  funnel: DashboardFunnelStage[];
  judge_dimensions?: Record<string, Record<string, Metric>>;
};
type EvaluationApproval = {
  required: boolean;
  status: string;
  source: string;
  recorded: boolean;
  approval_id: string | null;
  approver_ref: string | null;
  decided_at: string | null;
  reason_hash: string | null;
};

const percent = (value: number | null | undefined) => value == null ? "N/A" : `${(value * 100).toFixed(2)}%`;
const metricValue = (metric: Distribution | undefined, key: "mean" | "p50" | "p95" | "p99") => metric?.[key] == null ? "N/A" : metric[key]!.toFixed(2);
const metricWithUnit = (metric: Distribution | undefined, key: "mean" | "p50" | "p95" | "p99", unit: string) => {
  const value = metricValue(metric, key);
  return value === "N/A" ? value : `${value} ${unit}`;
};
const metric = (report: EvalReport | null, name: string) => report?.performance_stats?.overall?.[name];

function csvCell(value: unknown): string {
  const text = value == null ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function downloadText(filename: string, content: string, mimeType: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mimeType }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function ScoreDistribution({ rows }: { rows: EvalCase[] }) {
  const buckets = [0, 1, 2, 3, 4].map((floor, index) => {
    const values = rows.map((row) => row.judge_score).filter((score): score is number => score != null && score >= floor && (index === 4 ? score <= 4 : score < floor + 1));
    return { label: index === 4 ? "4.0" : `${floor}.0–<${floor + 1}.0`, count: values.length };
  });
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
  return <div className={styles.scoreDistribution} aria-label="Judge 加权分数分布">
    {buckets.map((bucket) => <div className={styles.scoreDistributionBar} key={bucket.label}>
      <strong>{bucket.count}</strong><i><b style={{ height: `${bucket.count / max * 100}%` }} /></i><span>{bucket.label}</span>
    </div>)}
  </div>;
}

function RubricHeatmap({ dimensionsByTrack, tracks }: { dimensionsByTrack: Record<string, Record<string, Metric>>; tracks: string[] }) {
  const dimensions = [...new Set(tracks.flatMap((track) => Object.keys(dimensionsByTrack[track] ?? {})))].sort();
  if (tracks.length === 0 || dimensions.length === 0) return <p className={styles.empty}>当前报告没有足够的 Judge 维度数据，无法生成热力图。</p>;
  return <div className={styles.tableScroller}><table className={`${styles.dataTable} ${styles.heatmapTable}`}><caption>Track × Rubric 平均分（由服务端报告聚合；0～4 分）</caption><thead><tr><th>Track</th>{dimensions.map((dimension) => <th key={dimension}>{dimension}</th>)}</tr></thead><tbody>{tracks.map((track) => <tr key={track}><th scope="row">{track}</th>{dimensions.map((dimension) => { const value = dimensionsByTrack[track]?.[dimension]?.mean ?? null; return <td key={dimension} className={value === null ? styles.heatmapMissing : value < 2 ? styles.heatmapLow : value < 3 ? styles.heatmapMid : styles.heatmapHigh}>{value === null ? "N/A" : value.toFixed(2)}</td>; })}</tr>)}</tbody></table></div>;
}

function EvaluationFunnel({ dashboard }: { dashboard: EvalDashboardDto }) {
  const selected = dashboard.counts.selected;
  const tones = ["funnelBlue", "funnelSlate", "funnelGreen", "funnelPurple", "funnelDark"];
  return <div className={styles.evaluationFunnel} aria-label="评测样本质量漏斗">
    {dashboard.funnel.map((stage, index) => { const ratio = selected && selected > 0 && stage.count !== null ? stage.count / selected : null; return <div className={styles.funnelRow} key={stage.id}>
      <span>{stage.label}</span><div className={styles.funnelTrack}><i className={styles[tones[index] ?? "funnelDark"]} style={{ width: ratio === null ? "100%" : `${Math.max(3, Math.min(100, ratio * 100))}%` }} /></div><strong>{stage.count === null ? "N/A" : `${stage.count} / ${selected ?? "N/A"}`}</strong><small>{ratio === null ? "未提供聚合" : `${(ratio * 100).toFixed(2)}%`}</small>
      {index < dashboard.funnel.length - 1 ? <em aria-hidden="true">↓</em> : null}
    </div>; })}
    <p className={styles.flowNote}>漏斗由服务端 Dashboard DTO 计算；若 Hard/Judge 聚合数据缺失，显示 N/A，不推断为失败。Gate 状态也以该 DTO 为准。</p>
  </div>;
}

function LayeredMetrics({ report }: { report: EvalReport }) {
  const hard = report.hard_dimension_stats ?? {};
  const hardRows = Object.entries(hard).flatMap(([track, dimensions]) =>
    Object.entries(dimensions).map(([name, value]) => ({ track, name, value })),
  );
  const multi = report.multiturn_stats;
  const multiMetric = (value: MultiTurnMetric | undefined) => value?.mean == null ? "N/A" : percent(value.mean);
  const catalog = report.catalog_stats;
  return <section className={styles.observabilityCard} aria-label="分层评测指标">
    <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Layered evaluation</p><h3>分层指标与独立分母</h3></div><span>Hard / Multi-turn / Catalog</span></div>
    {hardRows.length === 0 ? <p className={styles.empty}>没有 Hard Dimension 聚合证据，显示 N/A。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><caption>Hard Dimension（按 Track 独立统计）</caption><thead><tr><th>Track</th><th>维度</th><th>分子</th><th>分母</th><th>通过率</th></tr></thead><tbody>{hardRows.map(({ track, name, value }) => <tr key={`${track}-${name}`}><td>{track}</td><td>{name}</td><td>{value.passed}</td><td>{value.total}</td><td>{percent(value.rate)}</td></tr>)}</tbody></table></div>}
    {multi ? <div className={styles.metricGrid}><article><span>多轮场景</span><strong>{multi.scenario_count}</strong><small>报告状态：{multi.status ?? "N/A"}</small></article><article><span>Intent Coverage</span><strong>{multiMetric(multi.intent_coverage)}</strong><small>{multi.intent_coverage?.count ?? 0} 条有效轨迹</small></article><article><span>暴露意图准确率</span><strong>{multiMetric(multi.exposed_intent_accuracy)}</strong><small>排除 evaluation noise</small></article><article><span>Task Success</span><strong>{multiMetric(multi.task_success_rate)}</strong><small>噪声轨迹不进入 Agent 分母</small></article><article><span>Evaluation Noise</span><strong>{multi.evaluation_noise_count}</strong><small>单独修订模拟器/场景</small></article></div> : <p className={styles.flowNote}>当前批次没有多轮报告，指标保持 N/A。</p>}
    {catalog ? <div className={styles.tableScroller}><table className={styles.dataTable}><caption>商品长尾 Track（不并入总体通过率）</caption><thead><tr><th>Track</th><th>样本数</th><th>指标</th><th>分子</th><th>分母</th><th>比率</th></tr></thead><tbody>{Object.entries(catalog).map(([track, values]) => { const record = values as Record<string, unknown>; return Object.entries(record).filter(([, value]) => typeof value === "object" && value !== null).map(([name, value]) => { const metricValue = value as Record<string, unknown>; return <tr key={`${track}-${name}`}><td>{track}</td><td>{typeof record.case_count === "number" ? record.case_count : "N/A"}</td><td>{name}</td><td>{typeof metricValue.passed === "number" ? metricValue.passed : "N/A"}</td><td>{typeof metricValue.total === "number" ? metricValue.total : "N/A"}</td><td>{typeof metricValue.rate === "number" ? percent(metricValue.rate) : "N/A"}</td></tr>; }); }).flat()}</tbody></table></div> : <p className={styles.flowNote}>当前批次没有商品长尾报告，指标保持 N/A。</p>}
    {report.rag_stats ? <div className={styles.tableScroller}><table className={styles.dataTable}><caption>RAG Evidence（按证据 ID 聚合）</caption><thead><tr><th>指标</th><th>分子</th><th>分母</th><th>比率</th><th>状态</th></tr></thead><tbody>{(["recall_at_k", "precision_at_k", "grounding_rate"] as const).map((name) => { const value = report.rag_stats?.[name]; return <tr key={name}><td>{name}</td><td>{typeof value?.numerator === "number" ? value.numerator : "N/A"}</td><td>{typeof value?.denominator === "number" ? value.denominator : "N/A"}</td><td>{typeof value?.rate === "number" ? percent(value.rate) : "N/A"}</td><td>{typeof value?.evidence_status === "string" ? value.evidence_status : "N/A"}</td></tr>; })}</tbody></table></div> : <p className={styles.flowNote}>当前批次没有 RAG Evidence 聚合，指标保持 N/A。</p>}
    {report.failure_reason_stats ? <p className={styles.flowNote}>失败原因维度已落盘：{Object.entries(report.failure_reason_stats).map(([name, count]) => `${name} ${count}`).join(" · ") || "N/A"}</p> : null}
  </section>;
}

export function EvalDashboard() {
  const [summaries, setSummaries] = useState<EvalSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<EvalReport | null>(null);
  const [dashboard, setDashboard] = useState<EvalDashboardDto | null>(null);
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [caseDetail, setCaseDetail] = useState<EvalCaseDetail | null>(null);
  const [detailSelection, setDetailSelection] = useState<{ caseId: string; attemptNo: number } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [failedOnly, setFailedOnly] = useState(true);
  const [trackFilter, setTrackFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [casesError, setCasesError] = useState<string | null>(null);
  const [approval, setApproval] = useState<EvaluationApproval | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [approvalForbidden, setApprovalForbidden] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<EvalSummary[]>("/v1/evals")
      .then((items) => { setSummaries(items); setSelected((current) => current ?? items[0]?.eval_run_id ?? null); })
      .catch((reason: unknown) => { setError(reason instanceof Error ? reason.message : "评测列表加载失败"); setForbidden(reason instanceof ApiError && reason.status === 403); })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) { setReport(null); setDashboard(null); setCases([]); setCaseDetail(null); setDetailSelection(null); return; }
    setCaseDetail(null); setDetailSelection(null);
    setLoading(true); setError(null); setDashboardError(null); setCasesError(null); setForbidden(false);
    const load = async () => {
      const [reportResult, dashboardResult, casesResult] = await Promise.allSettled([
        api<EvalReport>(`/v1/evals/${selected}`),
        api<EvalDashboardDto>(`/v1/evals/${selected}/dashboard`),
        api<{ items: EvalCase[] }>(`/v1/evals/${selected}/cases?failed_only=${failedOnly}&limit=200`),
      ]);
      if (reportResult.status === "fulfilled") setReport(reportResult.value);
      else {
        setError(reportResult.reason instanceof Error ? reportResult.reason.message : "评测报告加载失败");
        setForbidden(reportResult.reason instanceof ApiError && reportResult.reason.status === 403);
      }
      if (dashboardResult.status === "fulfilled") setDashboard(dashboardResult.value);
      else setDashboardError(dashboardResult.reason instanceof Error ? dashboardResult.reason.message : "评测 Dashboard 加载失败");
      if (casesResult.status === "fulfilled") setCases(casesResult.value.items);
      else setCasesError(casesResult.reason instanceof Error ? casesResult.reason.message : "Case 加载失败");
      setLoading(false);
    };
    void load();
  }, [selected, failedOnly]);

  useEffect(() => {
    if (!selected) return;
    const caseId = new URLSearchParams(window.location.search).get("case_id");
    if (caseId) setDetailSelection({ caseId, attemptNo: 1 });
  }, [selected, failedOnly]);

  useEffect(() => {
    if (!selected || report?.human_approval?.required !== true) {
      setApproval(null);
      setApprovalError(null);
      setApprovalForbidden(false);
      return;
    }
    setApprovalError(null);
    setApprovalForbidden(false);
    void api<EvaluationApproval>(`/v1/evals/${selected}/approval`)
      .then(setApproval)
      .catch((reason: unknown) => { setApprovalError(reason instanceof Error ? reason.message : "审批记录加载失败"); setApprovalForbidden(reason instanceof ApiError && reason.status === 403); });
  }, [selected, report?.human_approval?.required]);

  useEffect(() => {
    if (!selected || !detailSelection) { setCaseDetail(null); return; }
    setDetailLoading(true);
    api<EvalCaseDetail>(`/v1/evals/${selected}/cases/${encodeURIComponent(detailSelection.caseId)}?attempt_no=${detailSelection.attemptNo}`)
      .then(setCaseDetail)
      .catch((reason: unknown) => setCasesError(reason instanceof Error ? reason.message : "Case 详情加载失败"))
      .finally(() => setDetailLoading(false));
  }, [selected, detailSelection]);

  if (loading && !report && summaries.length === 0) return <PageState kind="loading" title="正在读取评测报告…" />;
  if (error && !report && summaries.length === 0) return <div className={styles.insightPage}><PageState kind={forbidden ? "forbidden" : "error"} title="评测报告加载失败" detail={error} /><MultiTurnExplorer /></div>;
  if (summaries.length === 0) return <div className={styles.insightPage}><PageState kind="empty" title="暂无静态评测批次" detail="当前仍可查看独立的多轮评测报告。" /><MultiTurnExplorer /></div>;

  const overallDimensions = dashboard?.judge_dimensions?.overall ?? {};
  const tracks = Object.keys(report?.tracks ?? {});
  const activeTrack = trackFilter === "all" || tracks.includes(trackFilter) ? trackFilter : "all";
  const allRows = report?.results ?? [];
  const filteredRows = activeTrack === "all" ? allRows : allRows.filter((row) => row.track === activeTrack);
  const filteredCases = activeTrack === "all" ? cases : cases.filter((item) => item.track === activeTrack);
  const attemptGroups = [...filteredRows.reduce<Map<string, EvalCase[]>>((groups, row) => {
    const group = groups.get(row.case_id) ?? [];
    group.push(row);
    groups.set(row.case_id, group);
    return groups;
  }, new Map())].sort(([, left], [, right]) => right.length - left.length);
  const evaluationGroups = [...summaries.reduce<Map<string, EvalSummary[]>>((groups, item) => {
    const key = `${item.runtime ?? "unknown runtime"} · ${item.dataset_id ?? "unknown dataset"}`;
    const group = groups.get(key) ?? [];
    group.push(item);
    groups.set(key, group);
    return groups;
  }, new Map())];
  const handleExportJson = () => {
    if (report) downloadText(`commerce-agent-${report.eval_run_id}.json`, JSON.stringify(report, null, 2), "application/json;charset=utf-8");
  };
  const handleExportCsv = () => {
    const headers = ["case_id", "track", "attempt_no", "hard_pass", "judge_pass", "final_pass", "judge_score", "judge_error"];
    const rows = filteredRows.map((row, index) => {
      const attemptNo = filteredRows.slice(0, index).filter((candidate) => candidate.case_id === row.case_id).length + 1;
      return [row.case_id, row.track, attemptNo, row.hard_pass, row.judge_pass, row.final_pass, row.judge_score, row.judge_error].map(csvCell).join(",");
    });
    downloadText(`commerce-agent-${report?.eval_run_id ?? "eval"}-cases.csv`, [headers.join(","), ...rows].join("\n"), "text/csv;charset=utf-8");
  };
  const handleExportMarkdown = async () => {
    if (!selected) return;
    try {
      const response = await fetch(`/v1/evals/${encodeURIComponent(selected)}/markdown`);
      if (!response.ok) throw new Error(`Markdown 报告下载失败（${response.status}）`);
      downloadText(
        `commerce-agent-${selected}.md`,
        await response.text(),
        "text/markdown;charset=utf-8",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Markdown 报告下载失败");
    }
  };
  const humanApproval = approval ?? dashboard?.human_approval ?? (report?.human_approval ? {
    required: report.human_approval.required === true,
    status: report.human_approval.status ?? "unknown",
    source: report.human_approval.source ?? "unknown",
  } : { required: false, status: "not_required", source: "N/A" });
  const approvalGranted = humanApproval.status === "approved" || humanApproval.status === "approved_by_human";
  const approvalState = !humanApproval.required ? styles.flowPendingBox : approvalGranted ? styles.flowPassed : styles.flowBlocked;
  const approvalLabel = !humanApproval.required ? "不需要真人审批" : approvalGranted ? "真人已批准" : "真人审批待完成";
  return <div className={styles.insightPage}>
    <section className={styles.observabilityCard}>
      <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Evaluation catalog</p><h3>按 Runtime / Dataset 分组</h3></div><span>报告元数据来自服务端</span></div>
      <div className={styles.scoreGrid}>{evaluationGroups.map(([group, groupItems]) => <article key={group}><div><span>{group}</span><strong>{groupItems.length} 批</strong></div><small>{groupItems.map((item) => `${item.dataset_version ?? "unknown"} · ${item.eval_run_id.slice(0, 8)}`).join(" / ")}</small><small>Hash：{groupItems[0]?.dataset_hash ?? "N/A"}</small></article>)}</div>
      <p className={styles.flowNote}>deterministic、live、synthetic、Shadow 和 Canary 只按服务端报告元数据分组；缺失元数据显示 unknown，不推断运行类型。</p>
    </section>
    <section className={styles.toolbar}><div><strong>评测批次</strong><span>自动化评测提供发布证据，不代替 Skill 真人审批</span></div><div className={styles.toolbarActions}><label>选择批次<select value={selected ?? ""} onChange={(event) => setSelected(event.target.value)}>{summaries.map((item) => <option key={item.eval_run_id} value={item.eval_run_id}>{item.eval_run_id.slice(0, 8)} · {item.status}</option>)}</select></label>{report ? <StatusTag value={report.status} /> : null}<button type="button" className={styles.secondaryButton} onClick={handleExportJson} disabled={!report}>导出 JSON</button><button type="button" className={styles.secondaryButton} onClick={handleExportCsv} disabled={!report}>导出 Case CSV</button><button type="button" className={styles.secondaryButton} onClick={() => void handleExportMarkdown()} disabled={!selected}>导出 Markdown</button></div></section>
    {error ? <p className={styles.error} role="alert">{error}</p> : null}
    {dashboardError ? <PageState kind="partial" title="评测 Dashboard 不可用" detail={`${dashboardError}；报告原始聚合仍可查看。`} /> : null}
    {casesError ? <PageState kind="partial" title="Case 下钻不完整" detail={`${casesError}；当前批次的汇总指标仍可查看。`} /> : null}
    {report ? <>
      <section className={styles.metricGrid}>
        <article><span>首次通过率</span><strong>{percent(report.first_pass_rate)}</strong><small>第一次 attempt</small></article>
        <article><span>{report.repetitions ?? 1} 次全通过率</span><strong>{percent(report.all_repetitions_pass_rate)}</strong><small>稳定性指标，不等于线上能力</small></article>
        <article><span>最终通过 Case</span><strong>{report.passed_cases ?? 0}/{report.selected_cases ?? 0}</strong><small>{report.failed_cases ?? 0} 个失败</small></article>
        <article><span>Release Gate</span><strong>{dashboard?.gate.release_gate == null ? "N/A" : dashboard.gate.release_gate ? "通过" : "未通过"}</strong><small>{report.self_judged ? "同模型 Judge，仅临时调试" : report.judge === "on" ? "独立 Judge" : "Judge 未启用"}</small></article>
      </section>
      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Evaluation flow</p><h3>评测与发布证据链</h3></div><span>{report.mode}</span></div>
        <div className={styles.approvalFlow}><article className={dashboard?.gate.hard_gate === "pass" ? styles.flowPassed : styles.flowBlocked}><span>1</span><strong>Hard Gate</strong><small>规则与安全断言</small></article><i>→</i><article className={report.judge === "on" ? styles.flowPassed : styles.flowPendingBox}><span>2</span><strong>LLM as Judge</strong><small>Rubric 多维评分</small></article><i>→</i><article className={dashboard?.gate.release_gate ? styles.flowPassed : styles.flowBlocked}><span>3</span><strong>Release Gate</strong><small>{dashboard?.gate.status === "incomplete" ? "证据不完整" : "独立性与完整性"}</small></article><i>→</i><article className={approvalState}><span>4</span><strong>{approvalLabel}</strong><small>{humanApproval.required ? `状态：${humanApproval.status}` : "该批次未声明审批要求"}</small></article></div>
        <div className={styles.reviewPanel} aria-label="自动评测与真人审批边界"><h3>自动评测没有真人在线时</h3><p>本批次仍可产出 Hard Gate、Judge 和 Release Gate 报告，但这些结果只代表评测证据，不代表已获上线授权。</p>{approvalError ? <PageState kind={approvalForbidden ? "forbidden" : "partial"} title="审批记录暂不可用" detail={`${approvalError}；报告仍保持原有 pending 边界。`} /> : null}<div className={styles.reviewDetails}><div><span>审批要求</span><strong>{humanApproval.required ? "需要" : "未声明"}</strong></div><div><span>当前状态</span><strong><StatusTag value={humanApproval.status} /></strong></div><div><span>审批来源</span><strong>{humanApproval.source}</strong></div><div><span>已记录</span><strong>{"recorded" in humanApproval ? (humanApproval.recorded ? "是" : "否") : "N/A"}</strong></div><div><span>线上命中</span><strong>{humanApproval.required && !approvalGranted ? "不进入 Active / Canary" : "以发布 Gate 为准"}</strong></div><div><span>超时处置</span><strong>{humanApproval.required && !approvalGranted ? "到期投影为 EXPIRED" : "N/A"}</strong></div></div><p className={styles.flowNote}>恢复人工审批后，审批人仍需重新核对安全、质量、成本和时延 Gate；系统不会用“无人审批”自动批准。</p></div>
        <dl className={styles.decisionFacts}><div><dt>Runtime</dt><dd>{report.runtime ?? "unknown"}</dd></div><div><dt>Dataset</dt><dd>{report.dataset_id ? `${report.dataset_id} / ${report.dataset_version ?? "unknown"}` : "unknown"}</dd></div><div><dt>Dataset hash</dt><dd>{report.dataset_hash ?? "unknown"}</dd></div><div><dt>Manifest hash</dt><dd>{report.manifest_hash ?? "unknown"}</dd></div><div><dt>Runtime hash</dt><dd>{report.runtime_hash ?? "unknown"}</dd></div><div><dt>报告协议</dt><dd>{report.schema_version ?? "unknown"}</dd></div><div><dt>持久化</dt><dd>{report.persistence ?? "unknown"}</dd></div><div><dt>临时结果</dt><dd>{report.provisional == null ? "unknown" : report.provisional ? "是" : "否"}</dd></div></dl>
      </section>
      <LayeredMetrics report={report} />
      <MultiTurnExplorer />
      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Quality funnel</p><h3>样本经过各道门禁的数量</h3></div><span>防止只看一个总通过率</span></div>
        {dashboard ? <EvaluationFunnel dashboard={dashboard} /> : <PageState kind="partial" title="Dashboard DTO 暂不可用" detail="不在浏览器端重新推断漏斗或 Gate。" />}
      </section>
      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Latency · Token · Cost</p><h3>评测资源消耗</h3></div><span>Agent 与 Judge 分栏，缺失显示 N/A</span></div>
        <div className={styles.metricGrid}>
          <article><span>E2E P95</span><strong>{metricWithUnit(metric(report, "e2e_latency_ms"), "p95", "ms")}</strong><small>均值 {metricWithUnit(metric(report, "e2e_latency_ms"), "mean", "ms")}</small></article>
          <article><span>Agent 总 Token 均值</span><strong>{metricValue(metric(report, "agent_total_tokens"), "mean")}</strong><small>P95 {metricValue(metric(report, "agent_total_tokens"), "p95")}</small></article>
          <article><span>Agent 成本均值</span><strong>{metricValue(metric(report, "agent_cost_microusd"), "mean") === "N/A" ? "N/A" : `${metricValue(metric(report, "agent_cost_microusd"), "mean")} μUSD`}</strong><small>P95 {metricValue(metric(report, "agent_cost_microusd"), "p95") === "N/A" ? "N/A" : `${metricValue(metric(report, "agent_cost_microusd"), "p95")} μUSD`}</small></article>
          <article><span>Judge 成本均值</span><strong>{metricValue(metric(report, "judge_cost_microusd"), "mean") === "N/A" ? "N/A" : `${metricValue(metric(report, "judge_cost_microusd"), "mean")} μUSD`}</strong><small>不计入 Agent 单次成本</small></article>
          <article><span>数据合成成本</span><strong>{report.synthesis_cost_microusd == null ? "N/A" : `${report.synthesis_cost_microusd} μUSD`}</strong><small>没有独立生成账单时不推断为 0</small></article>
        </div>
        <table className={styles.dataTable}><caption>资源消耗分布（均值 / P50 / P95 / P99）</caption><thead><tr><th>范围</th><th>指标</th><th>样本</th><th>均值</th><th>P50</th><th>P95</th><th>P99</th></tr></thead><tbody>{Object.entries(report.performance_stats?.overall ?? {}).filter(([, value]) => value.count > 0).map(([name, value]) => <tr key={name}><td>overall</td><td>{name}</td><td>{value.count}</td><td>{metricValue(value, "mean")}</td><td>{metricValue(value, "p50")}</td><td>{metricValue(value, "p95")}</td><td>{metricValue(value, "p99")}</td></tr>)}</tbody></table>
      </section>
      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Rubric</p><h3>Judge 各指标平均分</h3></div><span>0～4 分</span></div>
        {Object.keys(overallDimensions).length === 0 ? <p className={styles.empty}>当前报告没有 Judge 维度分；显示 N/A，不按 0 分处理。</p> : <div className={styles.scoreGrid}>{Object.entries(overallDimensions).map(([name, metric]) => <article key={name}><div><span>{name}</span><strong>{metric.mean.toFixed(2)}</strong></div><i><b style={{ width: `${Math.min(100, metric.mean / 4 * 100)}%` }} /></i><small>{metric.count} 次评分</small></article>)}</div>}
        <div className={styles.evalSubToolbar}><label>观察 Track<select value={activeTrack} onChange={(event) => setTrackFilter(event.target.value)}><option value="all">全部 Track</option>{tracks.map((track) => <option key={track} value={track}>{track}</option>)}</select></label><span>颜色越深表示平均分越高；没有 Judge 证据保持 N/A</span></div>
        <RubricHeatmap dimensionsByTrack={dashboard?.judge_dimensions ?? {}} tracks={activeTrack === "all" ? tracks : [activeTrack]} />
        <div className={styles.distributionLayout}><div><h4 className={styles.miniHeading}>加权总分分布</h4><ScoreDistribution rows={filteredRows} /></div><div className={styles.distributionNote}><strong>{filteredRows.filter((row) => row.judge_score != null).length} 次 Judge 评分</strong><span>按 attempt 统计，不把重复运行折叠成一个高分。</span><span>分数区间用于发现离散度，不能单独替代 Hard Gate 或安全门禁。</span></div></div>
      </section>
      {report.safety_stats ? <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Safety Gate</p><h3>高危样本安全指标</h3></div><span className={report.safety_stats.p0_failure_count === 0 && report.safety_stats.safe_next_step_critical_pass && report.safety_stats.reviewed?.gate_pass !== false ? styles.flowPassed : styles.flowBlocked}>{report.safety_stats.reviewed?.status === "incomplete" ? "人工标签不完整" : report.safety_stats.p0_failure_count === 0 && report.safety_stats.safe_next_step_critical_pass && report.safety_stats.reviewed?.gate_pass !== false ? "可继续评估" : "阻断"}</span></div>
        <div className={styles.metricGrid}><article><span>高危样本</span><strong>{report.safety_stats.high_risk_cases}</strong><small>Safety hard gate</small></article><article><span>P0 hard fail</span><strong>{report.safety_stats.p0_failure_count}</strong><small>必须为 0</small></article><article><span>safe_next_step</span><strong>{percent(report.safety_stats.safe_next_step_pass_rate)}</strong><small>{report.safety_stats.safe_next_step_failure_count} 个失败</small></article></div>
        {report.safety_stats.reviewed ? <div className={styles.reviewDetails}><strong>人工复核误差（不由检测命中推断）</strong><div><span>复核状态</span><strong>{report.safety_stats.reviewed.status}</strong></div><div><span>安全漏判</span><strong>{report.safety_stats.reviewed.false_negative_count == null ? "N/A" : `${report.safety_stats.reviewed.false_negative_count} · ${percent(report.safety_stats.reviewed.false_negative_rate)}`}</strong></div><div><span>低风险误拒绝</span><strong>{report.safety_stats.reviewed.false_rejection_count == null ? "N/A" : `${report.safety_stats.reviewed.false_rejection_count} · ${percent(report.safety_stats.reviewed.false_rejection_rate)}`}</strong></div><div><span>复核 Gate</span><strong>{report.safety_stats.reviewed.gate_pass == null ? "N/A" : report.safety_stats.reviewed.gate_pass ? "通过" : "阻断"}</strong></div><small>已复核 {report.safety_stats.reviewed.reviewed_case_count} · 缺失标签 {report.safety_stats.reviewed.missing_label_count}；没有完整人工标签时保持 N/A。</small></div> : <p className={styles.flowNote}>当前报告没有人工复核标签，漏判/误拒绝保持 N/A；Safety 命中数不代表质量结论。</p>}
      </section> : null}
      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Tracks</p><h3>分 Track 通过情况</h3></div><span>避免总体均值掩盖短板</span></div>
        {!report.tracks || Object.keys(report.tracks).length === 0 ? <p className={styles.empty}>暂无 Track 聚合数据。</p> : <table className={styles.dataTable}><thead><tr><th>Track</th><th>Cases</th><th>Attempts</th><th>Hard 通过</th><th>Judge 通过</th><th>Final 通过</th></tr></thead><tbody>{Object.entries(report.tracks).map(([name, metric]) => <tr key={name}><td>{name}</td><td>{metric.selected}</td><td>{metric.attempts ?? "N/A"}</td><td>{metric.hard_pass}</td><td>{metric.judge_pass}</td><td>{metric.final_pass}</td></tr>)}</tbody></table>}
        <div className={styles.attemptSummary}><strong>Attempt 下钻</strong><span>{attemptGroups.length} 个 Case · {filteredRows.length} 次执行</span></div>
        {attemptGroups.length === 0 ? <p className={styles.empty}>没有可展示的 attempt 记录。</p> : <div className={styles.tableScroller}><table className={styles.dataTable}><caption>同一 Case 的重复运行结果（当前筛选：{activeTrack === "all" ? "全部 Track" : activeTrack}）</caption><thead><tr><th>Case</th><th>Track</th><th>Attempt</th><th>Hard</th><th>Judge</th><th>Final</th><th>加权分</th><th>Trace</th></tr></thead><tbody>{attemptGroups.flatMap(([caseId, rows]) => rows.map((row, index) => <tr key={`${caseId}-${index}`}><td>{caseId}</td><td>{row.track}</td><td>第 {index + 1} 次</td><td>{row.hard_pass ? "通过" : "失败"}</td><td>{row.judge_pass == null ? "N/A" : row.judge_pass ? "通过" : "失败"}</td><td>{row.final_pass == null ? "N/A" : row.final_pass ? "通过" : "失败"}</td><td>{row.judge_score == null ? "N/A" : row.judge_score.toFixed(2)}</td><td><button type="button" className={styles.inlineLinkButton} onClick={() => setDetailSelection({ caseId, attemptNo: index + 1 })}>查看流程</button></td></tr>))}</tbody></table></div>}
        {detailLoading ? <p className={styles.empty}>正在读取 Case 流程…</p> : null}
        {caseDetail ? <CaseDetail detail={caseDetail} /> : <p className={styles.flowNote}>点击任意 attempt 的“查看流程”，下钻到路由、执行、证据和 Judge 判定。</p>}
      </section>
      <section className={styles.observabilityCard}>
        <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Cases</p><h3>Case 结果与失败原因</h3></div><label className={styles.inlineCheck}><input type="checkbox" checked={failedOnly} onChange={(event) => setFailedOnly(event.target.checked)} />仅失败</label></div>
        {filteredCases.length === 0 ? <p className={styles.empty}>{failedOnly ? "没有失败 Case。" : "没有 Case 结果。"}</p> : <div className={styles.evalCaseList}>{filteredCases.map((item) => <article className={styles.evalCase} key={`${item.case_id}-${item.track}`}><strong>{item.case_id}</strong><span>{item.track}</span><p>Hard：{item.hard_pass ? "通过" : "失败"} · Judge：{item.judge_pass === null ? "N/A" : item.judge_pass ? "通过" : "失败"} · Final：{item.final_pass === null ? "N/A" : item.final_pass ? "通过" : "失败"} · Judge 分：{item.judge_score ?? "N/A"}</p>{item.hard_fail_reasons.length > 0 ? <small>{item.hard_fail_reasons.join("，")}</small> : null}{item.judge_error ? <small>Judge 错误：{item.judge_error}</small> : null}<button type="button" className={styles.inlineLinkButton} onClick={() => setDetailSelection({ caseId: item.case_id, attemptNo: 1 })}>查看第 1 次流程</button></article>)}</div>}
      </section>
    </> : null}
  </div>;
}

function CaseDetail({ detail }: { detail: EvalCaseDetail }) {
  const statusClass = (status: string) => status === "done" ? styles.flowPassed : status === "failed" ? styles.flowBlocked : status === "warning" ? styles.flowWarningBox : styles.flowPendingBox;
  return <section className={styles.caseDetail} aria-label="Case 流程详情">
    <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Case Trace</p><h3>{detail.case_id ?? "unknown"} · 第 {detail.attempt_no} 次</h3></div><span>{detail.track}</span></div>
    <div className={styles.caseFlow}>{detail.flow.map((step, index) => <div className={styles.caseFlowItem} key={step.id}><article className={statusClass(step.status)}><strong>{index + 1}. {step.label}</strong><small>{step.detail}</small></article>{index < detail.flow.length - 1 ? <i aria-hidden="true">→</i> : null}</div>)}</div>
    <div className={styles.traceFacts}><div><span>Run Trace</span><strong>{detail.trace.run_id ? <a href={`/runs/${encodeURIComponent(detail.trace.run_id)}`}>{detail.trace.run_id}</a> : "N/A"}</strong></div><div><span>Route</span><strong>{detail.trace.route ?? "N/A"}</strong></div><div><span>Intent</span><strong>{detail.trace.intent ?? "N/A"}</strong></div><div><span>Next action</span><strong>{detail.trace.next_action ?? "N/A"}</strong></div><div><span>状态</span><strong><StatusTag value={detail.trace.status} /></strong></div><div><span>工具调用</span><strong>{detail.trace.tools_called.length ? detail.trace.tools_called.join("、") : "无"}</strong></div><div><span>回复</span><strong>{detail.trace.response_present == null ? "N/A" : detail.trace.response_present ? "已生成" : "无"}</strong></div><div><span>失败关联</span><strong>{detail.failure_ids?.length ? detail.failure_ids.map((id) => <a key={id} href={`/failures/${encodeURIComponent(id)}`}>{id.slice(0, 8)}… </a>) : "N/A"}</strong></div></div>
    <div className={styles.detailColumns}><div><h4>证据引用</h4><p className={styles.detailLabel}>RAG / Trace evidence</p>{detail.trace.evidence_ids.length ? <div className={styles.tagList}>{detail.trace.evidence_ids.map((id) => <code key={id}>{id}</code>)}</div> : <p className={styles.empty}>无证据引用</p>}</div><div><h4>Judge 摘要</h4><p className={styles.detailLabel}>加权分：{detail.judge.score == null ? "N/A" : detail.judge.score.toFixed(2)}</p>{detail.judge.summary ? <p className={styles.judgeSummary}>{detail.judge.summary}</p> : <p className={styles.empty}>没有可展示的 Judge 摘要</p>}{Object.keys(detail.judge.dimensions).length ? <div className={styles.tagList}>{Object.entries(detail.judge.dimensions).map(([name, score]) => <span key={name}>{name}：{score}/4</span>)}</div> : null}{detail.judge.evidence.length ? <div className={styles.tagList}>{detail.judge.evidence.map((item, index) => <span key={`${item}-${index}`}>{item}</span>)}</div> : null}</div></div>
    {detail.hard.fail_reasons.length || detail.judge.error || detail.runtime_error ? <div className={styles.detailWarnings}>{detail.hard.fail_reasons.map((reason) => <span key={reason}>Hard：{reason}</span>)}{detail.judge.error ? <span>Judge：{detail.judge.error}</span> : null}{detail.runtime_error ? <span>Runtime：{detail.runtime_error}</span> : null}</div> : null}
  </section>;
}
