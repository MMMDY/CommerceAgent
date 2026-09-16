import { useEffect, useMemo, useRef, useState } from "react";

import { resolveRoute } from "./routes";
import styles from "./styles/App.module.css";

type Message = { id: string; role: "user" | "assistant"; content: string; sequence_no: number; run_id: string | null };
type Conversation = { id: string; status: string };
type Preview = { mutation_type: string; resource_ref: string; operation: string; summary: string; impact: Record<string, unknown>; amount: { value: number; currency: string }; channel: string; estimated_time: string; policy_version: string };
type Run = { run_id: string; conversation_id?: string; status: string; status_label?: string; status_description?: string; current_step: string; step_count: number; allowed_actions?: string[]; retryable?: boolean; preview?: Preview | null; confirmation_expires_at?: string | null; token_refresh_required?: boolean };
type EventItem = { id: number; type: string; step_id: string; payload: Record<string, unknown>; occurred_at?: string };
type StateNode = { status: string; label: string; description: string; terminal: boolean; transitions: string[] };
type Evidence = { evidence_id: string; source_uri: string; version: string; excerpt: string };
type HumanReview = { ticket_id: string; run_id: string; status: string; reason_code: string; operation?: string | null; details: Record<string, unknown>; created_at: string; resolved_at?: string | null; resolution?: string | null };
type Scenario = { id: string; label: string; prompt: string };
type EvalSummary = { eval_run_id: string; status: string; selected_cases: number; completed_cases: number; passed_cases: number; failed_cases: number; judge: string; mode: string; repetitions: number };
type EvalCase = { case_id: string; track: string; hard_pass: boolean; judge_pass: boolean | null; final_pass: boolean | null; judge_score: number | null; hard_fail_reasons: string[]; judge_error: string | null };

class ApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly detail?: unknown) {
    super(message);
  }
}

const fallbackScenarios: Scenario[] = [
  { id: "order_status", label: "查订单", prompt: "查询我的订单状态" },
  { id: "product_info", label: "查商品", prompt: "TAH6206 支持什么蓝牙版本？" },
  { id: "policy", label: "查政策", prompt: "请说明退款政策" },
] as const;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) {
    let detail: unknown;
    try { detail = await response.json(); } catch { /* preserve the HTTP status */ }
    const message = typeof detail === "object" && detail !== null && "detail" in detail
      ? String((detail as { detail: unknown }).detail)
      : `请求失败（${response.status}）`;
    throw new ApiError(response.status, message, detail);
  }
  return response.json() as Promise<T>;
}

export function App() {
  const route = resolveRoute(window.location.pathname);
  const [drawer, setDrawer] = useState<"navigation" | "trace" | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [scenarios, setScenarios] = useState<readonly Scenario[]>(fallbackScenarios);
  const [run, setRun] = useState<Run | null>(null);
  // The plaintext confirmation token is intentionally memory-only.
  const [confirmationToken, setConfirmationToken] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sseConnected, setSseConnected] = useState(false);
  const [evals, setEvals] = useState<EvalSummary[]>([]);
  const [evalCases, setEvalCases] = useState<EvalCase[]>([]);
  const [evalFilter, setEvalFilter] = useState<"all" | "failed">("all");
  const [stateMachine, setStateMachine] = useState<StateNode[]>([]);
  const [humanReview, setHumanReview] = useState<HumanReview | null>(null);
  const [humanReviewLoading, setHumanReviewLoading] = useState(false);
  const [humanReviewError, setHumanReviewError] = useState<string | null>(null);
  const [humanReviewReload, setHumanReviewReload] = useState(0);
  const [reviewNote, setReviewNote] = useState("");
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const submitGuard = useRef(false);

  const closeDrawer = () => setDrawer(null);
  const conversationPath = useMemo(
    () => (conversation ? `/v1/conversations/${conversation.id}` : null),
    [conversation],
  );
  const terminalRun = !run || ["completed", "failed", "cancelled", "expired"].includes(run.status);
  const canContinueCurrentRun = run?.allowed_actions?.includes("continue") ?? false;
  const inputLocked = busy || (!!run && !terminalRun && !canContinueCurrentRun);
  const currentState = stateMachine.find((item) => item.status === run?.status);

  const createConversation = async () => {
    if (busy) return;
    try {
      const created = await api<Conversation>("/v1/conversations", {
        method: "POST",
        body: JSON.stringify({ client_request_id: `web-new-${crypto.randomUUID()}` }),
      });
      setConversation(created);
      setMessages([]);
      setEvents([]);
      setEvidence([]);
      setRun(null);
      setConfirmationToken(null);
      setHumanReview(null);
      setHumanReviewError(null);
      setReviewNote("");
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法新建会话");
    }
  };

  useEffect(() => {
    const restoreOrCreate = async () => {
      const conversations = await api<Conversation[]>("/v1/conversations");
      const savedId = window.localStorage.getItem("commerce-agent-conversation-id");
      const restored = conversations.find((item) => item.id === savedId) ?? conversations[0];
      if (restored) {
        setConversation(restored);
        return;
      }
      const created = await api<Conversation>("/v1/conversations", {
        method: "POST",
        body: JSON.stringify({ client_request_id: `web-${Date.now()}` }),
      });
      setConversation(created);
    };
    void restoreOrCreate().catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (conversation) window.localStorage.setItem("commerce-agent-conversation-id", conversation.id);
  }, [conversation]);

  useEffect(() => {
    void api<Scenario[]>("/internal/v1/demo/scenarios")
      .then(setScenarios)
      .catch(() => setScenarios(fallbackScenarios));
  }, []);

  useEffect(() => {
    void api<{ states: StateNode[] }>("/v1/runtime/state-machine")
      .then((response) => setStateMachine(response.states))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!conversationPath) return;
    void api<Message[]>(`${conversationPath}/messages`).then(async (loaded) => {
      setMessages(loaded);
      const active = await api<{ run: Run | null }>(`${conversationPath}/active-run`);
      if (!active.run) return;
      const [savedRun, trace, citedEvidence] = await Promise.all([
        api<Run>(`/v1/runs/${active.run.run_id}`),
        api<EventItem[]>(`/v1/runs/${active.run.run_id}/timeline`),
        api<Evidence[]>(`/v1/runs/${active.run.run_id}/evidence`),
      ]);
      setRun(savedRun); setEvents(trace); setEvidence(citedEvidence);
      if (savedRun.token_refresh_required) setConfirmationToken(null);
    }).catch((reason: Error) => setError(reason.message));
  }, [conversationPath]);

  useEffect(() => {
    if (route !== "evals") return;
    void api<EvalSummary[]>("/v1/evals").then(async (items) => {
      setEvals(items);
      const latest = items[0];
      if (!latest) return;
      const response = await api<{ items: EvalCase[] }>(`/v1/evals/${latest.eval_run_id}/cases?failed_only=${evalFilter === "failed"}`);
      setEvalCases(response.items);
    }).catch((reason: Error) => setError(reason.message));
  }, [route, evalFilter]);

  useEffect(() => {
    if (!run?.run_id || !conversationPath) return;
    const stream = new EventSource(`/v1/runs/${run.run_id}/stream`);
    stream.onopen = () => setSseConnected(true);
    stream.onerror = () => {
      setSseConnected(false);
      void Promise.all([
        api<Run>(`/v1/runs/${run.run_id}`),
        api<EventItem[]>(`/v1/runs/${run.run_id}/timeline`),
        api<Evidence[]>(`/v1/runs/${run.run_id}/evidence`),
      ]).then(([savedRun, trace, citedEvidence]) => {
        setRun(savedRun); setEvents(trace); setEvidence(citedEvidence);
        if (savedRun.token_refresh_required) setConfirmationToken(null);
      }).catch(() => undefined);
    };
    const appendEvent = (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as Record<string, unknown>;
        const id = Number(event.lastEventId);
        if (!Number.isInteger(id) || id <= 0) return;
        setEvents((current) => current.some((item) => item.id === id)
          ? current
          : [...current, { id, type: event.type, step_id: "stream", payload }]);
      } catch { /* malformed events never become UI state */ }
    };
    ["run_created", "model_request_started", "model_request_succeeded", "model_request_failed", "decision_validation_failed", "recovery_attempt_started", "recovery_attempt_succeeded", "recovery_attempt_failed", "tool_called", "tool_observed", "tool_request_started", "tool_request_succeeded", "tool_request_failed", "assistant_response", "terminal_response_published", "step_completed", "waiting_for_user", "handoff_resolved", "failed"].forEach((name) => {
      stream.addEventListener(name, appendEvent as EventListener);
    });
    return () => stream.close();
  }, [run?.run_id]);

  useEffect(() => {
    if (!run?.run_id || !conversationPath) return;
    const timer = window.setInterval(() => {
      void Promise.all([
        api<Run>(`/v1/runs/${run.run_id}`),
        api<EventItem[]>(`/v1/runs/${run.run_id}/timeline`),
        api<Message[]>(`${conversationPath}/messages`),
      ]).then(([savedRun, trace, loadedMessages]) => {
        setRun(savedRun);
        setEvents(trace);
        setMessages(loadedMessages);
      }).catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [run?.run_id, conversationPath]);

  useEffect(() => {
    if (!run?.run_id || run.status !== "waiting_human") {
      setHumanReview(null);
      setHumanReviewLoading(false);
      setHumanReviewError(null);
      setReviewNote("");
      return;
    }
    setHumanReviewLoading(true);
    setHumanReviewError(null);
    void api<HumanReview>(`/v1/runs/${run.run_id}/human-review`)
      .then(setHumanReview)
      .catch((reason: Error) => {
        setHumanReview(null);
        setHumanReviewError(reason.message);
      })
      .finally(() => setHumanReviewLoading(false));
  }, [run?.run_id, run?.status, humanReviewReload]);

  const send = async (content: string) => {
    if (!conversation || !content.trim() || busy || submitGuard.current) return;
    submitGuard.current = true;
    setBusy(true); setError(null);
    const clientMessageId = `web-msg-${Date.now()}`;
    try {
      const result = await api<{ message_id: string; run_id: string; run_status: string; confirmation_token?: string | null; preview?: Preview | null; confirmation_expires_at?: string | null; token_refresh_required?: boolean }>(
        `/v1/conversations/${conversation.id}/messages`, { method: "POST", body: JSON.stringify({ content, client_message_id: clientMessageId }) },
      );
      setInput("");
      const loaded = await api<Message[]>(`${conversationPath}/messages`);
      setMessages(loaded);
      setRun({ run_id: result.run_id, status: result.run_status, current_step: "route", step_count: 0, preview: result.preview, confirmation_expires_at: result.confirmation_expires_at, token_refresh_required: result.token_refresh_required });
      setConfirmationToken(result.confirmation_token ?? null);
      const [trace, citedEvidence] = await Promise.all([
        api<EventItem[]>(`/v1/runs/${result.run_id}/timeline`),
        api<Evidence[]>(`/v1/runs/${result.run_id}/evidence`),
      ]);
      setEvents(trace); setEvidence(citedEvidence);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        const active = await api<{ run: Run | null }>(`${conversationPath}/active-run`).catch(() => ({ run: null }));
        if (active.run) setRun(active.run);
        setError("当前会话已有未结束任务，已连接到该任务；请等待它完成后再发送。 ");
      } else setError(reason instanceof Error ? reason.message : "请求失败");
    } finally { submitGuard.current = false; setBusy(false); }
  };

  const refreshConfirmation = async () => {
    if (!run) return;
    try {
      const refreshed = await api<{ confirmation_token: string; preview: Preview; run_status: string; expires_at: string }>(`/v1/runs/${run.run_id}/confirmations/refresh`, { method: "POST" });
      setConfirmationToken(refreshed.confirmation_token);
      setRun((current) => current ? { ...current, status: refreshed.run_status, preview: refreshed.preview, confirmation_expires_at: refreshed.expires_at, token_refresh_required: false } : current);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法刷新确认"); }
  };

  const decideConfirmation = async (decision: "accept" | "reject") => {
    if (!run || !confirmationToken || busy) return;
    setBusy(true); setError(null);
    try {
      const result = await api<{ run_status: string; accepted: boolean }>(`/v1/runs/${run.run_id}/confirmations`, {
        method: "POST",
        body: JSON.stringify({ decision, confirmation_token: confirmationToken, idempotency_key: `web-confirm-${crypto.randomUUID()}` }),
      });
      setConfirmationToken(null);
      setRun((current) => current ? { ...current, status: result.run_status, token_refresh_required: false } : current);
      const [loaded, trace] = await Promise.all([api<Message[]>(`${conversationPath}/messages`), api<EventItem[]>(`/v1/runs/${run.run_id}/events`)]);
      setMessages(loaded); setEvents(trace);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "确认失败");
      if (reason instanceof ApiError && reason.status === 409) {
        try {
          const current = await api<Run>(`/v1/runs/${run.run_id}`);
          setRun(current);
          setConfirmationToken(null);
          if (current.status === "waiting_confirmation" && current.token_refresh_required) {
            await refreshConfirmation();
          }
        } catch (reloadError) {
          setError(reloadError instanceof Error ? reloadError.message : "无法刷新服务端状态");
        }
      }
    } finally { setBusy(false); }
  };

  const resolveHumanReview = async (outcome: "verified_success" | "verified_failure") => {
    if (!humanReview || reviewSubmitting || !reviewNote.trim()) return;
    setReviewSubmitting(true); setError(null);
    try {
      await api(`/internal/v1/handoffs/${humanReview.ticket_id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ outcome, resolution_note: reviewNote.trim() }),
      });
      const [savedRun, trace, loadedMessages] = await Promise.all([
        api<Run>(`/v1/runs/${humanReview.run_id}`),
        api<EventItem[]>(`/v1/runs/${humanReview.run_id}/timeline`),
        api<Message[]>(`${conversationPath}/messages`),
      ]);
      setRun(savedRun); setEvents(trace); setMessages(loadedMessages); setHumanReview(null); setReviewNote("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "人工审核提交失败");
    } finally { setReviewSubmitting(false); }
  };

  const retryRun = async () => {
    if (!run || !conversationPath || busy || !run.allowed_actions?.includes("retry")) return;
    setBusy(true); setError(null);
    try {
      const result = await api<{ run_id: string; run_status: string }>(
        `/v1/runs/${run.run_id}/retry`,
        {
          method: "POST",
          body: JSON.stringify({ client_message_id: `web-retry-${crypto.randomUUID()}` }),
        },
      );
      const [savedRun, trace, loadedMessages] = await Promise.all([
        api<Run>(`/v1/runs/${result.run_id}`),
        api<EventItem[]>(`/v1/runs/${result.run_id}/timeline`),
        api<Message[]>(`${conversationPath}/messages`),
      ]);
      setRun(savedRun); setEvents(trace); setMessages(loadedMessages);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重试失败");
    } finally { setBusy(false); }
  };

  return (
    <main className={styles.shell} aria-label="CommerceAgent 演示工作台">
      <button className={`${styles.drawerToggle} ${styles.navigationToggle}`} type="button" onClick={() => setDrawer("navigation")}>导航</button>
      <aside className={`${styles.sidePanel} ${styles.leftPanel} ${drawer === "navigation" ? styles.drawerOpen : ""}`} aria-label="会话与预置场景">
        <button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button>
        <p className={styles.eyebrow}>CommerceAgent · 透明执行演示</p><h1>客服 Agent</h1>
        <nav aria-label="主要页面"><a href="/">对话</a><a href="/runs/demo">Run Trace</a><a href="/evals">评测</a></nav>
        <button className={styles.newConversation} type="button" onClick={() => void createConversation()} disabled={busy}>新建会话</button>
        <div className={styles.scenarios}><p className={styles.eyebrow}>预置场景</p>{scenarios.map((scenario) => <button key={scenario.id} type="button" onClick={() => void send(scenario.prompt)} disabled={!conversation || inputLocked}>{scenario.label}</button>)}</div>
      </aside>
      <section className={styles.workspace} aria-live="polite">
        <p className={styles.eyebrow}>{route === "chat" ? "只读演示" : route}</p><h2>{route === "chat" ? "对话工作台" : route === "run" ? "执行详情" : "评测面板"}</h2>
        {route === "evals" ? <section className={styles.evalPanel} aria-label="评测结果"><div className={styles.statusBar}><span>批次：{evals.length}</span><button type="button" onClick={() => setEvalFilter("all")} disabled={evalFilter === "all"}>全部</button><button type="button" onClick={() => setEvalFilter("failed")} disabled={evalFilter === "failed"}>仅失败</button></div>{evals.length === 0 ? <p className={styles.empty}>暂无评测报告，可通过 POST /v1/evals 创建批次。</p> : evals.map((item) => <article className={styles.evalCard} key={item.eval_run_id}><h3>{item.eval_run_id}</h3><p>状态：{item.status} · Judge：{item.judge} · 模式：{item.mode}</p><p>进度：{item.completed_cases}/{item.selected_cases} · Hard 通过：{item.passed_cases} · 失败：{item.failed_cases}</p></article>)}{evalCases.length > 0 ? <><h3>失败 Case 详情</h3><div className={styles.evalCaseList}>{evalCases.map((item) => <article className={styles.evalCase} key={`${item.case_id}-${item.track}`}><strong>{item.case_id}</strong><span>{item.track}</span><p>Hard：{item.hard_pass ? "通过" : "失败"} · Judge：{item.judge_pass === null ? "未评分" : item.judge_pass ? "通过" : "失败"} · Final：{item.final_pass === null ? "未完成" : item.final_pass ? "通过" : "失败"}</p>{item.hard_fail_reasons.length > 0 ? <small>{item.hard_fail_reasons.join(", ")}</small> : null}{item.judge_error ? <small>Judge 错误：{item.judge_error}</small> : null}</article>)}</div></> : null}</section> : route !== "chat" ? <p>从左侧返回对话，或通过 API 查询已持久化的 run 与事件。</p> : <>
          <div className={styles.statusBar}><span>{conversation ? "会话已连接" : "正在连接…"}{sseConnected ? " · SSE 已连接" : ""}</span>{run ? <span>Run · {run.status}</span> : null}</div>
          {run ? <div className={styles.activityInline}><strong>{run.status_label ?? currentState?.label ?? run.status}</strong><span>{run.status_description ?? currentState?.description ?? "正在同步服务端状态"}</span></div> : null}
          <div className={styles.messageList} aria-label="消息流">{messages.length === 0 ? <p className={styles.empty}>选择一个预置场景或输入问题开始。</p> : messages.map((message) => <article className={message.role === "user" ? styles.userMessage : styles.assistantMessage} key={message.id}><span>{message.role === "user" ? "你" : "Agent"}</span><p>{message.content}</p></article>)}</div>
          {run?.status === "failed" && run.allowed_actions?.includes("retry") ? <section className={styles.confirmationCard} aria-label="执行结果操作"><p className={styles.eyebrow}>执行未完成</p><p>{run.status_description ?? "本次处理未能完成"}</p><button type="button" onClick={() => void retryRun()} disabled={busy}>{busy ? "重试中…" : "重试本次请求"}</button></section> : null}
          {run?.status === "waiting_confirmation" && run.preview ? <section className={styles.confirmationCard} aria-label="操作确认"><p className={styles.eyebrow}>请确认操作</p><h3>{run.preview.summary}</h3><p>{run.preview.resource_ref} · {run.preview.channel}</p><p>金额：{run.preview.amount.value} {run.preview.amount.currency} · {run.preview.estimated_time}</p>{run.preview.impact.address ? <p>地址：{String(run.preview.impact.address)}</p> : null}{run.confirmation_expires_at ? <p>确认有效期至：{new Date(run.confirmation_expires_at).toLocaleString()}</p> : null}{confirmationToken ? <div className={styles.confirmationActions}><button type="button" onClick={() => void decideConfirmation("accept")} disabled={busy}>确认提交</button><button type="button" onClick={() => void decideConfirmation("reject")} disabled={busy}>拒绝</button></div> : <button type="button" onClick={() => void refreshConfirmation()} disabled={busy}>刷新确认</button>}</section> : null}
          {error ? <p role="alert" className={styles.error}>{error}</p> : null}
          <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void send(input); }}><input aria-label="输入消息" value={input} onChange={(event) => setInput(event.target.value)} placeholder={inputLocked ? "Agent 正在处理当前任务…" : "例如：订单 ORD-DEMO-001 到哪了？"} disabled={!conversation || inputLocked} /><button type="submit" disabled={!conversation || inputLocked || !input.trim()}>{inputLocked ? "处理中" : "发送"}</button></form>
        </>}
      </section>
      <button className={`${styles.drawerToggle} ${styles.traceToggle}`} type="button" onClick={() => setDrawer("trace")}>Trace</button>
      <aside className={`${styles.sidePanel} ${styles.rightPanel} ${drawer === "trace" ? styles.drawerOpen : ""}`} aria-label="Agent 状态与执行日志"><button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button><p className={styles.eyebrow}>Agent 工作状态</p>{run ? <section className={styles.activitySummary}><strong>{run.status_label ?? currentState?.label ?? run.status}</strong><span>{run.status_description ?? currentState?.description ?? "正在同步服务端状态"}</span><small>当前步骤：{run.current_step} · 已完成 {run.step_count} 步</small></section> : <p>尚无活动任务</p>}<div className={styles.stateMachine} aria-label="Agent 状态机">{stateMachine.map((node) => <div className={`${styles.stateNode} ${node.status === run?.status ? styles.stateCurrent : ""} ${node.status === "completed" && run?.status === "completed" ? styles.stateDone : ""}`} key={node.status}><span className={styles.stateDot} /><span>{node.label}</span></div>)}</div>{run?.status === "waiting_human" ? (humanReview ? <section className={styles.humanReview} aria-label="人工处理"><div className={styles.reviewHeader}><p className={styles.eyebrow}>人工处理</p><span>待审核</span></div><h3>{humanReview.reason_code}</h3><p className={styles.reviewDescription}>Agent 已暂停自动执行，请真人核对以下信息后决定是否批准。</p>{humanReview.operation ? <p><strong>操作：</strong>{humanReview.operation}</p> : null}<div className={styles.reviewDetails}>{Object.entries(humanReview.details).map(([key, value]) => <div key={key}><span>{key}</span><strong>{String(value)}</strong></div>)}</div><textarea aria-label="人工审核说明" value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="填写审核说明" rows={3} disabled={reviewSubmitting} /><div className={styles.reviewActions}><button type="button" onClick={() => void resolveHumanReview("verified_success")} disabled={reviewSubmitting || !reviewNote.trim()}>审核批准</button><button type="button" onClick={() => void resolveHumanReview("verified_failure")} disabled={reviewSubmitting || !reviewNote.trim()}>不批准</button></div></section> : <section className={styles.humanReview} aria-label="人工处理"><div className={styles.reviewHeader}><p className={styles.eyebrow}>人工处理</p><span>{humanReviewLoading ? "加载中" : "需要重试"}</span></div><h3>人工审核窗口</h3><p className={styles.reviewDescription}>{humanReviewLoading ? "正在加载审核工单，请稍候…" : (humanReviewError ?? "暂时无法加载审核工单。")}</p>{!humanReviewLoading ? <button type="button" onClick={() => setHumanReviewReload((value) => value + 1)} disabled={reviewSubmitting}>重新加载审核工单</button> : null}</section>) : null}<div className={styles.timelineHeader}><p className={styles.eyebrow}>实时执行日志</p><span>{sseConnected ? "实时" : "同步中"}</span></div><div className={styles.timeline}>{events.map((event) => <details className={styles.timelineItem} key={event.id} open={event.id === events[events.length - 1]?.id}><summary><code>#{event.id}</code><span>{event.type}</span><small>{event.step_id}</small></summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details>)}</div>{evidence.length > 0 ? <section className={styles.evidenceList} aria-label="回答证据"><p className={styles.eyebrow}>回答证据</p>{evidence.map((item) => <article className={styles.evidenceCard} key={item.evidence_id}><code>{item.source_uri}</code><small>版本 {item.version}</small><p>{item.excerpt}</p></article>)}</section> : null}</aside>
      {drawer ? <button className={styles.backdrop} aria-label="关闭抽屉" type="button" onClick={closeDrawer} /> : null}
    </main>
  );
}
