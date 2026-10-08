import { useEffect, useState } from "react";

import styles from "../styles/App.module.css";
import { api } from "../api/client";
import { PageState } from "./PageState";
import { StatusTag } from "./StatusTag";

type Metric = { mean: number | null; count: number; denominator?: number | null };
type MultiTurnSummary = {
  report_id: string;
  dataset_id?: string;
  dataset_version?: string;
  runtime?: string;
  status?: string;
  scenario_count?: number;
  completed_count?: number;
  incomplete_count?: number;
  evaluation_noise_count?: number;
  intent_coverage?: Metric;
  exposed_intent_accuracy?: Metric;
  task_success_rate?: Metric;
  judge?: { evaluated_count?: number; mean_weighted_score?: number | null; status?: string; model?: string | null };
  human_review?: { status?: string; reviewed_count?: number; minimum_count?: number; gate_pass?: boolean | null };
};
type Dialogue = {
  scenario_id: string;
  dialogue_id?: string;
  status?: string;
  termination_reason?: string;
  intent_coverage?: number | null;
  agenda_progress?: number | null;
  exposed_intent_accuracy?: number | null;
  task_success?: boolean | null;
  evaluation_noise?: boolean;
  intent_summary?: { key_intents?: string[]; raised_key_intents?: string[]; addressed_key_intents?: string[] };
  feedback?: { category?: string; code?: string; severity?: string; turn_ids?: number[] }[];
  judge?: { weighted_score?: number | null; judge_pass?: boolean | null; error_code?: string | null };
};
type MultiTurnDashboard = MultiTurnSummary & { dialogues: Dialogue[] };
type Turn = {
  turn_id: number;
  user_action?: { action?: string; message?: string; emotion?: string; reason_code?: string };
  agent_trace?: { route?: string; intent?: string; next_action?: string; response?: string; status?: string; tools_called?: string[]; evidence_ids?: string[] };
  intent_states?: Record<string, string>;
  transitions?: { intent?: string; from_state?: string; to_state?: string; evidence?: string[] }[];
  verifier_pass?: boolean | null;
};
type MultiTurnTrace = Dialogue & { report_id: string; turns: Turn[] };

const percent = (value: number | null | undefined) => value == null ? "N/A" : `${(value * 100).toFixed(2)}%`;
const metricPercent = (value: Metric | undefined) => percent(value?.mean);

export function MultiTurnExplorer() {
  const [reports, setReports] = useState<MultiTurnSummary[]>([]);
  const [selectedReport, setSelectedReport] = useState<string | null>(null);
  const [dashboard, setDashboard] = useState<MultiTurnDashboard | null>(null);
  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const [trace, setTrace] = useState<MultiTurnTrace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<MultiTurnSummary[]>("/v1/multiturn-reports")
      .then((items) => { setReports(items); setSelectedReport(items[0]?.report_id ?? null); })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "多轮报告加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedReport) { setDashboard(null); setScenarioId(null); return; }
    setTrace(null);
    void api<MultiTurnDashboard>(`/v1/multiturn-reports/${encodeURIComponent(selectedReport)}/dashboard`)
      .then((value) => { setDashboard(value); setScenarioId(value.dialogues[0]?.scenario_id ?? null); })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "多轮 Dashboard 加载失败"));
  }, [selectedReport]);

  useEffect(() => {
    if (!selectedReport || !scenarioId) { setTrace(null); return; }
    void api<MultiTurnTrace>(`/v1/multiturn-reports/${encodeURIComponent(selectedReport)}/traces/${encodeURIComponent(scenarioId)}`)
      .then(setTrace)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "多轮轨迹加载失败"));
  }, [selectedReport, scenarioId]);

  if (loading) return <section className={styles.observabilityCard} aria-label="多轮评测"><PageState kind="loading" title="正在读取多轮报告…" /></section>;
  if (error && reports.length === 0) return <section className={styles.observabilityCard} aria-label="多轮评测"><PageState kind="partial" title="多轮报告暂不可用" detail={error} /></section>;
  if (reports.length === 0) return <section className={styles.observabilityCard} aria-label="多轮评测"><div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Multi-turn evaluation</p><h3>多轮轨迹</h3></div><span>独立报告与分母</span></div><p className={styles.empty}>当前没有多轮报告；不会从静态评测结果推断多轮能力。</p></section>;

  return <section className={styles.observabilityCard} aria-label="多轮评测轨迹">
    <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Multi-turn evaluation</p><h3>多轮意图状态与轨迹</h3></div><span>不并入静态 Case 总通过率</span></div>
    {error ? <p className={styles.flowWarningBox}>{error}</p> : null}
    <div className={styles.toolbar}><label>选择多轮报告<select value={selectedReport ?? ""} onChange={(event) => setSelectedReport(event.target.value)}>{reports.map((item) => <option key={item.report_id} value={item.report_id}>{item.report_id} · {item.dataset_version ?? "unknown"}</option>)}</select></label><StatusTag value={dashboard?.status ?? "loading"} /></div>
    {dashboard ? <>
      <div className={styles.metricGrid}>
        <article><span>多轮场景</span><strong>{dashboard.scenario_count ?? "N/A"}</strong><small>{dashboard.completed_count ?? 0} completed · {dashboard.incomplete_count ?? 0} incomplete</small></article>
        <article><span>Intent Coverage</span><strong>{metricPercent(dashboard.intent_coverage)}</strong><small>Simulator-side</small></article>
        <article><span>Exposed Intent Accuracy</span><strong>{metricPercent(dashboard.exposed_intent_accuracy)}</strong><small>排除 evaluation noise</small></article>
        <article><span>Task Success</span><strong>{metricPercent(dashboard.task_success_rate)}</strong><small>noise {dashboard.evaluation_noise_count ?? "N/A"}</small></article>
        <article><span>Multi-turn Judge</span><strong>{dashboard.judge?.mean_weighted_score == null ? "N/A" : dashboard.judge.mean_weighted_score.toFixed(2)}</strong><small>{dashboard.judge?.status ?? "incomplete"} · {dashboard.judge?.evaluated_count ?? 0} 条</small></article>
        <article><span>人工复核</span><strong>{dashboard.human_review?.status ?? "incomplete"}</strong><small>{dashboard.human_review?.reviewed_count ?? 0}/{dashboard.human_review?.minimum_count ?? "N/A"} 条 · Gate {dashboard.human_review?.gate_pass == null ? "N/A" : dashboard.human_review.gate_pass ? "通过" : "未通过"}</small></article>
      </div>
      <div className={styles.tableScroller}><table className={styles.dataTable}><caption>对话轨迹（选择后加载逐轮状态）</caption><thead><tr><th>Scenario</th><th>状态</th><th>终止原因</th><th>Intent Coverage</th><th>Task Success</th><th>Judge</th><th>反馈</th><th>Trace</th></tr></thead><tbody>{dashboard.dialogues.map((item) => <tr key={item.scenario_id}><td>{item.scenario_id}</td><td><StatusTag value={item.status ?? "unknown"} /></td><td>{item.termination_reason ?? "N/A"}</td><td>{percent(item.intent_coverage)}</td><td>{item.task_success == null ? "N/A" : item.task_success ? "通过" : "失败"}</td><td>{item.judge?.weighted_score == null ? "N/A" : `${item.judge.weighted_score.toFixed(2)} · ${item.judge.judge_pass ? "通过" : "失败"}`}</td><td>{item.feedback?.length ?? 0}</td><td><button type="button" className={styles.inlineLinkButton} onClick={() => setScenarioId(item.scenario_id)}>查看轨迹</button></td></tr>)}</tbody></table></div>
    </> : <p className={styles.empty}>正在读取多轮 Dashboard…</p>}
    {trace ? <MultiTurnTrace trace={trace} /> : <p className={styles.flowNote}>选择一个 Scenario 查看用户动作、Agent 处置和 Intent 状态转移。</p>}
  </section>;
}

function MultiTurnTrace({ trace }: { trace: MultiTurnTrace }) {
  return <div className={styles.multiTurnTrace}>
    <div className={styles.sectionHeading}><div><p className={styles.eyebrow}>Dialogue trace</p><h3>{trace.scenario_id}</h3></div><span>{trace.dialogue_id ?? "N/A"}</span></div>
    <div className={styles.traceFacts}><div><span>终止原因</span><strong>{trace.termination_reason ?? "N/A"}</strong></div><div><span>状态</span><strong><StatusTag value={trace.status ?? "unknown"} /></strong></div><div><span>Intent Coverage</span><strong>{percent(trace.intent_coverage)}</strong></div><div><span>Agenda Progress</span><strong>{percent(trace.agenda_progress)}</strong></div><div><span>反馈信号</span><strong>{trace.feedback?.length ?? 0}</strong></div></div>
    <ol className={styles.multiTurnTimeline}>{trace.turns.map((turn) => <li key={turn.turn_id}>
      <div className={styles.multiTurnTurnHeader}><strong>Turn {turn.turn_id}</strong><span>{turn.user_action?.action ?? "unknown"} · {turn.agent_trace?.status ?? "unknown"}</span><StatusTag value={turn.verifier_pass == null ? "N/A" : turn.verifier_pass ? "pass" : "fail"} /></div>
      <div className={styles.multiTurnTurnBody}><div><small>User action</small><p>{turn.user_action?.message ?? "N/A"}</p><span>{turn.user_action?.emotion ?? "neutral"} · {turn.user_action?.reason_code ?? "N/A"}</span></div><div><small>Agent response</small><p>{turn.agent_trace?.response || "N/A"}</p><span>{turn.agent_trace?.route ?? "N/A"} · {turn.agent_trace?.intent ?? "N/A"} · {turn.agent_trace?.next_action ?? "N/A"}</span></div></div>
      <div className={styles.tagList}>{Object.entries(turn.intent_states ?? {}).map(([intent, state]) => <span key={intent}>{intent}：{state}</span>)}{(turn.agent_trace?.tools_called ?? []).map((tool) => <code key={tool}>tool:{tool}</code>)}</div>
    </li>)}</ol>
    {trace.feedback?.length ? <div className={styles.detailWarnings}>{trace.feedback.map((signal, index) => <span key={`${signal.code}-${index}`}>{signal.category ?? "feedback"} · {signal.code ?? "unknown"} · Turn {signal.turn_ids?.join(", ") || "N/A"}</span>)}</div> : null}
  </div>;
}
