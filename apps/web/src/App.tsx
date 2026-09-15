import { useEffect, useMemo, useState } from "react";

import { resolveRoute } from "./routes";
import styles from "./styles/App.module.css";

type Message = { id: string; role: "user" | "assistant"; content: string; sequence_no: number; run_id: string | null };
type Conversation = { id: string; status: string };
type Preview = { mutation_type: string; resource_ref: string; operation: string; summary: string; impact: Record<string, unknown>; amount: { value: number; currency: string }; channel: string; estimated_time: string; policy_version: string };
type Run = { run_id: string; status: string; current_step: string; step_count: number; preview?: Preview | null; confirmation_expires_at?: string | null; token_refresh_required?: boolean };
type EventItem = { id: number; type: string; step_id: string; payload: Record<string, unknown> };
type Evidence = { evidence_id: string; source_uri: string; version: string; excerpt: string };
type Scenario = { id: string; label: string; prompt: string };
type EvalSummary = { eval_run_id: string; status: string; selected_cases: number; completed_cases: number; passed_cases: number; failed_cases: number; judge: string; mode: string; repetitions: number };
type EvalCase = { case_id: string; track: string; hard_pass: boolean; judge_pass: boolean | null; final_pass: boolean | null; judge_score: number | null; hard_fail_reasons: string[]; judge_error: string | null };

class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
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
  if (!response.ok) throw new ApiError(response.status, `请求失败（${response.status}）`);
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

  const closeDrawer = () => setDrawer(null);
  const conversationPath = useMemo(
    () => (conversation ? `/v1/conversations/${conversation.id}` : null),
    [conversation],
  );

  useEffect(() => {
    const restoreOrCreate = async () => {
      const conversations = await api<Conversation[]>("/v1/conversations");
      const savedId = window.localStorage.getItem("commerce-agent-conversation-id");
      const restored = conversations.find((item) => item.id === savedId) ?? conversations[0];
      if (restored) {
        // Do not reopen a terminally failed demo run as the active workbench.
        // It is safe to preserve the old conversation in the database while
        // giving the user a clean session after a transient model/validation
        // failure.  Active handoff/confirmation runs are kept and handled by
        // the send-time 503 recovery path below.
        try {
          const restoredMessages = await api<Message[]>(`/v1/conversations/${restored.id}/messages`);
          const latestRunId = [...restoredMessages].reverse().find((message) => message.run_id)?.run_id;
          if (latestRunId) {
            const latestRun = await api<Run>(`/v1/runs/${latestRunId}`);
            if (latestRun.status === "failed") {
              const fresh = await api<Conversation>("/v1/conversations", {
                method: "POST",
                body: JSON.stringify({ client_request_id: `web-failed-recovery-${crypto.randomUUID()}` }),
              });
              setError("上次演示任务失败，已自动新建会话。");
              setConversation(fresh);
              return;
            }
          }
        } catch {
          // The normal conversation restore below remains authoritative if the
          // optional failed-run probe is unavailable.
        }
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
    if (!conversationPath) return;
    void api<Message[]>(`${conversationPath}/messages`).then(async (loaded) => {
      setMessages(loaded);
      const latestRunId = [...loaded].reverse().find((message) => message.run_id)?.run_id;
      if (!latestRunId) return;
      const [savedRun, trace, citedEvidence] = await Promise.all([
        api<Run>(`/v1/runs/${latestRunId}`),
        api<EventItem[]>(`/v1/runs/${latestRunId}/events`),
        api<Evidence[]>(`/v1/runs/${latestRunId}/evidence`),
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
    if (!conversationPath) return;
    const stream = new EventSource(`${conversationPath}/stream`);
    stream.onopen = () => setSseConnected(true);
    stream.onerror = () => {
      setSseConnected(false);
      if (!run) return;
      void Promise.all([
        api<Run>(`/v1/runs/${run.run_id}`),
        api<EventItem[]>(`/v1/runs/${run.run_id}/events`),
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
    ["tool_called", "tool_observed", "step_completed", "waiting_for_user", "failed"].forEach((name) => {
      stream.addEventListener(name, appendEvent as EventListener);
    });
    return () => stream.close();
  }, [conversationPath, run]);

  const send = async (content: string) => {
    if (!conversation || !content.trim() || busy) return;
    setBusy(true); setError(null);
    const clientMessageId = `web-msg-${Date.now()}`;
    let targetConversation = conversation;
    let retriedWithFreshConversation = false;
    try {
      const postMessage = (conversationId: string, messageId: string) => api<{ message_id: string; run_id: string; run_status: string; confirmation_token?: string | null; preview?: Preview | null; confirmation_expires_at?: string | null; token_refresh_required?: boolean }>(
        `/v1/conversations/${conversationId}/messages`, { method: "POST", body: JSON.stringify({ content, client_message_id: messageId }) },
      );
      let result;
      try {
        result = await postMessage(targetConversation.id, clientMessageId);
      } catch (reason) {
        // A conversation with an unfinished handoff/confirmation run cannot
        // accept a second automatic run.  Fork a clean demo conversation and
        // retry once so the UI remains demonstrable after restoring history.
        if (!(reason instanceof ApiError) || reason.status !== 503) throw reason;
        const fresh = await api<Conversation>("/v1/conversations", {
          method: "POST",
          body: JSON.stringify({ client_request_id: `web-recovery-${crypto.randomUUID()}` }),
        });
        targetConversation = fresh;
        retriedWithFreshConversation = true;
        setConversation(fresh);
        setMessages([]); setEvents([]); setEvidence([]); setRun(null); setConfirmationToken(null);
        result = await postMessage(fresh.id, `${clientMessageId}-retry`);
      }
      if (result.run_status === "failed") {
        // A run can fail after the API has accepted the message (for example,
        // a provider returned a terminal decision with invalid citations).
        // Treat that durable failure like the 503 recovery case so a transient
        // model error never leaves the demonstrator stuck on a failed Run.
        const fresh = await api<Conversation>("/v1/conversations", {
          method: "POST",
          body: JSON.stringify({ client_request_id: `web-failed-recovery-${crypto.randomUUID()}` }),
        });
        targetConversation = fresh;
        retriedWithFreshConversation = true;
        setConversation(fresh);
        setMessages([]); setEvents([]); setEvidence([]); setRun(null); setConfirmationToken(null);
        result = await postMessage(fresh.id, `${clientMessageId}-failed-retry`);
      }
      setInput("");
      const targetPath = `/v1/conversations/${targetConversation.id}`;
      const loaded = await api<Message[]>(`${targetPath}/messages`);
      setMessages(loaded);
      setRun({ run_id: result.run_id, status: result.run_status, current_step: "route", step_count: 0, preview: result.preview, confirmation_expires_at: result.confirmation_expires_at, token_refresh_required: result.token_refresh_required });
      setConfirmationToken(result.confirmation_token ?? null);
      const [trace, citedEvidence] = await Promise.all([
        api<EventItem[]>(`/v1/runs/${result.run_id}/events`),
        api<Evidence[]>(`/v1/runs/${result.run_id}/evidence`),
      ]);
      setEvents(trace); setEvidence(citedEvidence);
      if (retriedWithFreshConversation) setError("原会话有未结束任务，已自动切换到新会话。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "请求失败"); }
    finally { setBusy(false); }
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

  return (
    <main className={styles.shell} aria-label="CommerceAgent 演示工作台">
      <button className={`${styles.drawerToggle} ${styles.navigationToggle}`} type="button" onClick={() => setDrawer("navigation")}>导航</button>
      <aside className={`${styles.sidePanel} ${styles.leftPanel} ${drawer === "navigation" ? styles.drawerOpen : ""}`} aria-label="会话与预置场景">
        <button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button>
        <p className={styles.eyebrow}>CommerceAgent · Phase 4</p><h1>客服 Agent</h1>
        <nav aria-label="主要页面"><a href="/">对话</a><a href="/runs/demo">Run Trace</a><a href="/evals">评测</a></nav>
        <div className={styles.scenarios}><p className={styles.eyebrow}>预置场景</p>{scenarios.map((scenario) => <button key={scenario.id} type="button" onClick={() => void send(scenario.prompt)}>{scenario.label}</button>)}</div>
      </aside>
      <section className={styles.workspace} aria-live="polite">
        <p className={styles.eyebrow}>{route === "chat" ? "只读演示" : route}</p><h2>{route === "chat" ? "对话工作台" : route === "run" ? "执行详情" : "评测面板"}</h2>
        {route === "evals" ? <section className={styles.evalPanel} aria-label="评测结果"><div className={styles.statusBar}><span>批次：{evals.length}</span><button type="button" onClick={() => setEvalFilter("all")} disabled={evalFilter === "all"}>全部</button><button type="button" onClick={() => setEvalFilter("failed")} disabled={evalFilter === "failed"}>仅失败</button></div>{evals.length === 0 ? <p className={styles.empty}>暂无评测报告，可通过 POST /v1/evals 创建批次。</p> : evals.map((item) => <article className={styles.evalCard} key={item.eval_run_id}><h3>{item.eval_run_id}</h3><p>状态：{item.status} · Judge：{item.judge} · 模式：{item.mode}</p><p>进度：{item.completed_cases}/{item.selected_cases} · Hard 通过：{item.passed_cases} · 失败：{item.failed_cases}</p></article>)}{evalCases.length > 0 ? <><h3>失败 Case 详情</h3><div className={styles.evalCaseList}>{evalCases.map((item) => <article className={styles.evalCase} key={`${item.case_id}-${item.track}`}><strong>{item.case_id}</strong><span>{item.track}</span><p>Hard：{item.hard_pass ? "通过" : "失败"} · Judge：{item.judge_pass === null ? "未评分" : item.judge_pass ? "通过" : "失败"} · Final：{item.final_pass === null ? "未完成" : item.final_pass ? "通过" : "失败"}</p>{item.hard_fail_reasons.length > 0 ? <small>{item.hard_fail_reasons.join(", ")}</small> : null}{item.judge_error ? <small>Judge 错误：{item.judge_error}</small> : null}</article>)}</div></> : null}</section> : route !== "chat" ? <p>从左侧返回对话，或通过 API 查询已持久化的 run 与事件。</p> : <>
          <div className={styles.statusBar}><span>{conversation ? "会话已连接" : "正在连接…"}{sseConnected ? " · SSE 已连接" : ""}</span>{run ? <span>Run · {run.status}</span> : null}</div>
          <div className={styles.messageList} aria-label="消息流">{messages.length === 0 ? <p className={styles.empty}>选择一个预置场景或输入问题开始。</p> : messages.map((message) => <article className={message.role === "user" ? styles.userMessage : styles.assistantMessage} key={message.id}><span>{message.role === "user" ? "你" : "Agent"}</span><p>{message.content}</p></article>)}</div>
          {run?.status === "waiting_confirmation" && run.preview ? <section className={styles.confirmationCard} aria-label="操作确认"><p className={styles.eyebrow}>请确认操作</p><h3>{run.preview.summary}</h3><p>{run.preview.resource_ref} · {run.preview.channel}</p><p>金额：{run.preview.amount.value} {run.preview.amount.currency} · {run.preview.estimated_time}</p>{run.preview.impact.address ? <p>地址：{String(run.preview.impact.address)}</p> : null}{run.confirmation_expires_at ? <p>确认有效期至：{new Date(run.confirmation_expires_at).toLocaleString()}</p> : null}{confirmationToken ? <div className={styles.confirmationActions}><button type="button" onClick={() => void decideConfirmation("accept")} disabled={busy}>确认提交</button><button type="button" onClick={() => void decideConfirmation("reject")} disabled={busy}>拒绝</button></div> : <button type="button" onClick={() => void refreshConfirmation()} disabled={busy}>刷新确认</button>}</section> : null}
          {error ? <p role="alert" className={styles.error}>{error}</p> : null}
          <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void send(input); }}><input aria-label="输入消息" value={input} onChange={(event) => setInput(event.target.value)} placeholder="例如：订单 ORD-DEMO-001 到哪了？" disabled={!conversation || busy} /><button type="submit" disabled={!conversation || busy || !input.trim()}>{busy ? "发送中" : "发送"}</button></form>
        </>}
      </section>
      <button className={`${styles.drawerToggle} ${styles.traceToggle}`} type="button" onClick={() => setDrawer("trace")}>Trace</button>
      <aside className={`${styles.sidePanel} ${styles.rightPanel} ${drawer === "trace" ? styles.drawerOpen : ""}`} aria-label="Trace 摘要"><button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button><p className={styles.eyebrow}>Run Trace</p>{run ? <><p>状态：{run.status}</p><p>当前步骤：{run.current_step}</p><p>已完成步骤：{run.step_count}</p></> : <p>尚无执行事件</p>}{events.map((event) => <div className={styles.traceEvent} key={event.id}><code>#{event.id}</code><span>{event.type}</span><small>{event.step_id}</small></div>)}{evidence.length > 0 ? <section className={styles.evidenceList} aria-label="回答证据"><p className={styles.eyebrow}>回答证据</p>{evidence.map((item) => <article className={styles.evidenceCard} key={item.evidence_id}><code>{item.source_uri}</code><small>版本 {item.version}</small><p>{item.excerpt}</p></article>)}</section> : null}</aside>
      {drawer ? <button className={styles.backdrop} aria-label="关闭抽屉" type="button" onClick={closeDrawer} /> : null}
    </main>
  );
}
