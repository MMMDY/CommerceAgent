import { useEffect, useMemo, useRef, useState } from "react";

import { resolveRoute, type RouteKind } from "./routes";
import { AgentFlow } from "./components/AgentFlow";
import { EvalDashboard } from "./components/EvalDashboard";
import { EvolutionLifecycle } from "./components/EvolutionLifecycle";
import { EventTimeline, eventLabel, eventStage, safeEventDetails } from "./components/EventTimeline";
import { OperationsDashboard } from "./components/OperationsDashboard";
import { RunInsight } from "./components/RunInsight";
import { api, ApiError } from "./api/client";
import type { Conversation, Evidence, EventItem, HumanReview, Message, Preview, Run, Scenario, StateNode } from "./contracts";
import { buildFeedbackRequest } from "./ui/feedback";
import styles from "./styles/App.module.css";

const routeLabels: Record<RouteKind, string> = {
  chat: "对话工作台",
  run: "执行详情",
  evals: "评测面板",
  operations: "运营总览",
  failures: "失败归因",
  failure: "失败详情",
  skills: "经验 Skill",
  skill: "Skill 详情",
  releases: "发布管理",
  release: "发布详情",
  not_found: "页面不存在",
};

const fallbackScenarios: Scenario[] = [
  { id: "order_status", label: "查订单", prompt: "查询我的订单状态" },
  { id: "product_info", label: "查商品", prompt: "TAH6206 支持什么蓝牙版本？" },
  { id: "policy", label: "查政策", prompt: "请说明退款政策" },
] as const;

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
  const [stateMachine, setStateMachine] = useState<StateNode[]>([]);
  const [humanReview, setHumanReview] = useState<HumanReview | null>(null);
  const [humanReviewLoading, setHumanReviewLoading] = useState(false);
  const [humanReviewError, setHumanReviewError] = useState<string | null>(null);
  const [humanReviewReload, setHumanReviewReload] = useState(0);
  const [reviewNote, setReviewNote] = useState("");
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
  const [feedbackDraft, setFeedbackDraft] = useState<"down" | null>(null);
  const [feedbackReason, setFeedbackReason] = useState("response_not_helpful");
  const [feedbackCorrection, setFeedbackCorrection] = useState("");
  const [feedbackConsent, setFeedbackConsent] = useState(false);
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
      setFeedback(null);
      setFeedbackDraft(null); setFeedbackReason("response_not_helpful"); setFeedbackCorrection(""); setFeedbackConsent(false);
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
    ["run_created", "safety_routed", "routing_shadow_compared", "routing_completed", "intent_classified", "policy_selected", "model_request_started", "model_request_succeeded", "model_request_failed", "decision_validation_failed", "recovery_attempt_started", "recovery_attempt_succeeded", "recovery_attempt_failed", "rag_retrieval_started", "rag_retrieval_succeeded", "tool_called", "tool_observed", "tool_request_started", "tool_request_succeeded", "tool_request_failed", "skill_matched", "release_assigned", "guardrail_passed", "guardrail_blocked", "fallback_activated", "assistant_response", "terminal_response_published", "step_completed", "waiting_for_user", "handoff_resolved", "failed"].forEach((name) => {
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
      setFeedback(null); setFeedbackDraft(null); setFeedbackCorrection(""); setFeedbackConsent(false);
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

  const submitFeedback = async (rating: "up" | "down", reasonCodes: string[] = [], correction?: string) => {
    if (!run || feedback || !terminalRun) return;
    try {
      await api(`/v1/runs/${run.run_id}/feedback`, {
        method: "POST",
        body: JSON.stringify(buildFeedbackRequest({
          rating,
          reasonCodes,
          correction,
          consent: Boolean(correction),
          idempotencyKey: `web-feedback-${run.run_id}-${rating}`,
        })),
      });
      setFeedback(rating);
      setFeedbackDraft(null);
    } catch {
      // Feedback is best effort and must never block the conversation.
    }
  };

  const runPageId = route === "run" ? window.location.pathname.match(/^\/runs\/([^/]+)$/)?.[1] ?? null : null;
  const lifecyclePage = (["failures", "failure", "skills", "skill", "releases", "release"] as const).find((item) => item === route);
  const traceHref = route === "run" ? window.location.pathname : run ? `/runs/${run.run_id}` : "/";

  return (
    <main className={styles.shell} aria-label="CommerceAgent 演示工作台">
      <button className={`${styles.drawerToggle} ${styles.navigationToggle}`} type="button" onClick={() => setDrawer("navigation")}>导航</button>
      <aside className={`${styles.sidePanel} ${styles.leftPanel} ${drawer === "navigation" ? styles.drawerOpen : ""}`} aria-label="会话与预置场景">
        <button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button>
        <p className={styles.eyebrow}>CommerceAgent · 透明执行演示</p><h1>客服 Agent</h1>
        <nav aria-label="主要页面"><a href="/">对话</a><a href={traceHref}>Run Trace</a><a href="/evals">评测</a><a href="/operations">运营</a><a href="/failures">失败归因</a><a href="/skills">Skills</a><a href="/releases">发布</a></nav>
        <button className={styles.newConversation} type="button" onClick={() => void createConversation()} disabled={busy}>新建会话</button>
        <div className={styles.scenarios}><p className={styles.eyebrow}>预置场景</p>{scenarios.map((scenario) => <button key={scenario.id} type="button" onClick={() => void send(scenario.prompt)} disabled={!conversation || inputLocked}>{scenario.label}</button>)}</div>
      </aside>
      <section className={`${styles.workspace} ${route === "chat" ? "" : styles.workspaceWide}`} aria-live="polite">
        <p className={styles.eyebrow}>{route === "chat" ? "只读演示" : "Agent Control Plane"}</p><h2>{routeLabels[route]}</h2>
        {route === "evals" ? <EvalDashboard /> : route === "run" && runPageId ? <RunInsight runId={decodeURIComponent(runPageId)} /> : route === "operations" ? <OperationsDashboard /> : lifecyclePage ? <EvolutionLifecycle page={lifecyclePage} /> : route === "not_found" ? <section className={styles.placeholderPanel} aria-label="页面不存在"><span className={styles.statusBadge}>404</span><h3>找不到这个页面</h3><p>请从左侧选择一个有效页面。</p></section> : <>
          <div className={styles.statusBar}><span>{conversation ? "会话已连接" : "正在连接…"}{sseConnected ? " · SSE 已连接" : run && !terminalRun ? " · SSE 断流 · 轮询回退" : ""}</span>{run ? <span>Run · {run.status}</span> : null}</div>
          {run ? <div className={styles.activityInline}><strong>{run.status_label ?? currentState?.label ?? run.status}</strong><span>{run.status_description ?? currentState?.description ?? "正在同步服务端状态"}</span></div> : null}
          <AgentFlow run={run} events={events} evidenceCount={evidence.length} />
          <EventTimeline events={events} />
          <div className={styles.messageList} aria-label="消息流">{messages.length === 0 ? <p className={styles.empty}>选择一个预置场景或输入问题开始。</p> : messages.map((message) => <article className={message.role === "user" ? styles.userMessage : styles.assistantMessage} key={message.id}><span>{message.role === "user" ? "你" : "Agent"}</span><p>{message.content}</p>{message.role === "assistant" && message.run_id === run?.run_id && terminalRun ? <div className={styles.feedbackActions} aria-label="回答反馈"><small>这次回答有帮助吗？</small><button type="button" onClick={() => void submitFeedback("up")} disabled={feedback !== null}>有帮助</button><button type="button" onClick={() => setFeedbackDraft("down")} disabled={feedback !== null}>需改进</button>{feedbackDraft && !feedback ? <div className={styles.feedbackDraft}><label>原因<select value={feedbackReason} onChange={(event) => setFeedbackReason(event.target.value)}><option value="response_not_helpful">回答没有解决问题</option><option value="response_inaccurate">回答可能不准确</option><option value="response_too_long">回答不够简洁</option><option value="other">其他</option></select></label><textarea aria-label="可选纠错" value={feedbackCorrection} onChange={(event) => setFeedbackCorrection(event.target.value)} placeholder="可选：提供脱敏后的改进建议" rows={2} /><label className={styles.feedbackConsent}><input type="checkbox" checked={feedbackConsent} onChange={(event) => setFeedbackConsent(event.target.checked)} disabled={!feedbackCorrection.trim()} />我授权将这段脱敏建议用于改进</label><div><button type="button" onClick={() => void submitFeedback("down", [feedbackReason], feedbackConsent && feedbackCorrection.trim() ? feedbackCorrection.trim() : undefined)}>提交反馈</button><button type="button" onClick={() => setFeedbackDraft(null)}>取消</button></div></div> : null}{feedback ? <small>已记录，感谢反馈</small> : null}</div> : null}</article>)}</div>
          {run?.status === "failed" && run.allowed_actions?.includes("retry") ? <section className={styles.confirmationCard} aria-label="执行结果操作"><p className={styles.eyebrow}>执行未完成</p><p>{run.status_description ?? "本次处理未能完成"}</p><button type="button" onClick={() => void retryRun()} disabled={busy}>{busy ? "重试中…" : "重试本次请求"}</button></section> : null}
          {run?.status === "waiting_confirmation" && run.preview ? <section className={styles.confirmationCard} aria-label="操作确认"><p className={styles.eyebrow}>请确认操作</p><h3>{run.preview.summary}</h3><p>{run.preview.resource_ref} · {run.preview.channel}</p><p>金额：{run.preview.amount.value} {run.preview.amount.currency} · {run.preview.estimated_time}</p>{run.preview.impact.address ? <p>地址：{String(run.preview.impact.address)}</p> : null}{run.confirmation_expires_at ? <p>确认有效期至：{new Date(run.confirmation_expires_at).toLocaleString()}</p> : null}{confirmationToken ? <div className={styles.confirmationActions}><button type="button" onClick={() => void decideConfirmation("accept")} disabled={busy}>确认提交</button><button type="button" onClick={() => void decideConfirmation("reject")} disabled={busy}>拒绝</button></div> : <button type="button" onClick={() => void refreshConfirmation()} disabled={busy}>刷新确认</button>}</section> : null}
          {error ? <p role="alert" className={styles.error}>{error}</p> : null}
          <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void send(input); }}><input aria-label="输入消息" value={input} onChange={(event) => setInput(event.target.value)} placeholder={inputLocked ? "Agent 正在处理当前任务…" : "例如：订单 ORD-DEMO-001 到哪了？"} disabled={!conversation || inputLocked} /><button type="submit" disabled={!conversation || inputLocked || !input.trim()}>{inputLocked ? "处理中" : "发送"}</button></form>
        </>}
      </section>
      <button className={`${styles.drawerToggle} ${styles.traceToggle}`} type="button" onClick={() => setDrawer("trace")}>Trace</button>
      <aside className={`${styles.sidePanel} ${styles.rightPanel} ${drawer === "trace" ? styles.drawerOpen : ""}`} aria-label="Agent 状态与执行日志"><button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button><p className={styles.eyebrow}>Agent 工作状态</p>{run ? <section className={styles.activitySummary}><strong>{run.status_label ?? currentState?.label ?? run.status}</strong><span>{run.status_description ?? currentState?.description ?? "正在同步服务端状态"}</span><small>当前步骤：{run.current_step} · 已完成 {run.step_count} 步</small></section> : <p>尚无活动任务</p>}<div className={styles.stateMachine} aria-label="Agent 状态机">{stateMachine.map((node) => <div className={`${styles.stateNode} ${node.status === run?.status ? styles.stateCurrent : ""} ${node.status === "completed" && run?.status === "completed" ? styles.stateDone : ""}`} key={node.status}><span className={styles.stateDot} /><span>{node.label}</span></div>)}</div>{run?.status === "waiting_human" ? (humanReview ? <section className={styles.humanReview} aria-label="人工处理"><div className={styles.reviewHeader}><p className={styles.eyebrow}>人工处理</p><span>待审核</span></div><h3>{humanReview.reason_code}</h3><p className={styles.reviewDescription}>Agent 已暂停自动执行，请真人核对以下信息后决定是否批准。</p>{humanReview.operation ? <p><strong>操作：</strong>{humanReview.operation}</p> : null}<div className={styles.reviewDetails}>{Object.entries(humanReview.details).map(([key, value]) => <div key={key}><span>{key}</span><strong>{String(value)}</strong></div>)}</div><textarea aria-label="人工审核说明" value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="填写审核说明" rows={3} disabled={reviewSubmitting} /><div className={styles.reviewActions}><button type="button" onClick={() => void resolveHumanReview("verified_success")} disabled={reviewSubmitting || !reviewNote.trim()}>审核批准</button><button type="button" onClick={() => void resolveHumanReview("verified_failure")} disabled={reviewSubmitting || !reviewNote.trim()}>不批准</button></div></section> : <section className={styles.humanReview} aria-label="人工处理"><div className={styles.reviewHeader}><p className={styles.eyebrow}>人工处理</p><span>{humanReviewLoading ? "加载中" : "需要重试"}</span></div><h3>人工审核窗口</h3><p className={styles.reviewDescription}>{humanReviewLoading ? "正在加载审核工单，请稍候…" : (humanReviewError ?? "暂时无法加载审核工单。")}</p>{!humanReviewLoading ? <button type="button" onClick={() => setHumanReviewReload((value) => value + 1)} disabled={reviewSubmitting}>重新加载审核工单</button> : null}</section>) : null}<div className={styles.timelineHeader}><p className={styles.eyebrow}>实时执行日志</p><span>{sseConnected ? "实时" : "同步中"}</span></div><div className={styles.timeline}>{events.map((event) => <details className={styles.timelineItem} key={event.id} open={event.id === events[events.length - 1]?.id}><summary><code>#{event.id}</code><span>{eventLabel(event.type)}</span><small>{eventStage(event.type, event.payload)} · {event.step_id}</small></summary><div className={styles.timelineSafeDetail}>{safeEventDetails(event.payload)}</div></details>)}</div>{evidence.length > 0 ? <section className={styles.evidenceList} aria-label="回答证据"><p className={styles.eyebrow}>回答证据</p>{evidence.map((item) => <article className={styles.evidenceCard} key={item.evidence_id}><code>{item.source_uri}</code><small>版本 {item.version}</small><p>{item.excerpt}</p></article>)}</section> : null}</aside>
      {drawer ? <button className={styles.backdrop} aria-label="关闭抽屉" type="button" onClick={closeDrawer} /> : null}
    </main>
  );
}
