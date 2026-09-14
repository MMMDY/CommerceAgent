import { useEffect, useMemo, useState } from "react";

import { resolveRoute } from "./routes";
import styles from "./styles/App.module.css";

type Message = { id: string; role: "user" | "assistant"; content: string; sequence_no: number };
type Conversation = { id: string; status: string };
type Run = { run_id: string; status: string; current_step: string; step_count: number };
type EventItem = { id: number; type: string; step_id: string; payload: Record<string, unknown> };

const scenarios = [
  { label: "查订单", text: "查询我的订单状态" },
  { label: "查商品", text: "TAH6206 支持什么蓝牙版本？" },
  { label: "查政策", text: "请说明退款政策" },
] as const;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) throw new Error(`请求失败（${response.status}）`);
  return response.json() as Promise<T>;
}

export function App() {
  const route = resolveRoute(window.location.pathname);
  const [drawer, setDrawer] = useState<"navigation" | "trace" | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const closeDrawer = () => setDrawer(null);
  const conversationPath = useMemo(
    () => (conversation ? `/v1/conversations/${conversation.id}` : null),
    [conversation],
  );

  useEffect(() => {
    void api<Conversation>("/v1/conversations", {
      method: "POST",
      body: JSON.stringify({ client_request_id: `web-${Date.now()}` }),
    }).then(setConversation).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!conversationPath) return;
    void api<Message[]>(`${conversationPath}/messages`).then(setMessages).catch((reason: Error) => setError(reason.message));
  }, [conversationPath]);

  const send = async (content: string) => {
    if (!conversation || !content.trim() || busy) return;
    setBusy(true); setError(null);
    const clientMessageId = `web-msg-${Date.now()}`;
    try {
      const result = await api<{ message_id: string; run_id: string; run_status: string }>(
        `${conversationPath}/messages`, { method: "POST", body: JSON.stringify({ content, client_message_id: clientMessageId }) },
      );
      setInput("");
      const loaded = await api<Message[]>(`${conversationPath}/messages`);
      setMessages(loaded);
      setRun({ run_id: result.run_id, status: result.run_status, current_step: "route", step_count: 0 });
      const trace = await api<EventItem[]>(`/v1/runs/${result.run_id}/events`);
      setEvents(trace);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "请求失败"); }
    finally { setBusy(false); }
  };

  return (
    <main className={styles.shell} aria-label="CommerceAgent 演示工作台">
      <button className={`${styles.drawerToggle} ${styles.navigationToggle}`} type="button" onClick={() => setDrawer("navigation")}>导航</button>
      <aside className={`${styles.sidePanel} ${styles.leftPanel} ${drawer === "navigation" ? styles.drawerOpen : ""}`} aria-label="会话与预置场景">
        <button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button>
        <p className={styles.eyebrow}>CommerceAgent · Phase 3</p><h1>客服 Agent</h1>
        <nav aria-label="主要页面"><a href="/">对话</a><a href="/runs/demo">Run Trace</a><a href="/evals">评测</a></nav>
        <div className={styles.scenarios}><p className={styles.eyebrow}>预置场景</p>{scenarios.map((scenario) => <button key={scenario.label} type="button" onClick={() => void send(scenario.text)}>{scenario.label}</button>)}</div>
      </aside>
      <section className={styles.workspace} aria-live="polite">
        <p className={styles.eyebrow}>{route === "chat" ? "只读演示" : route}</p><h2>{route === "chat" ? "对话工作台" : route === "run" ? "执行详情" : "评测面板"}</h2>
        {route !== "chat" ? <p>从左侧返回对话，或通过 API 查询已持久化的 run 与事件。</p> : <>
          <div className={styles.statusBar}><span>{conversation ? "会话已连接" : "正在连接…"}</span>{run ? <span>Run · {run.status}</span> : null}</div>
          <div className={styles.messageList} aria-label="消息流">{messages.length === 0 ? <p className={styles.empty}>选择一个预置场景或输入问题开始。</p> : messages.map((message) => <article className={message.role === "user" ? styles.userMessage : styles.assistantMessage} key={message.id}><span>{message.role === "user" ? "你" : "Agent"}</span><p>{message.content}</p></article>)}</div>
          {error ? <p role="alert" className={styles.error}>{error}</p> : null}
          <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void send(input); }}><input aria-label="输入消息" value={input} onChange={(event) => setInput(event.target.value)} placeholder="例如：订单 ORD-DEMO-001 到哪了？" disabled={!conversation || busy} /><button type="submit" disabled={!conversation || busy || !input.trim()}>{busy ? "发送中" : "发送"}</button></form>
        </>}
      </section>
      <button className={`${styles.drawerToggle} ${styles.traceToggle}`} type="button" onClick={() => setDrawer("trace")}>Trace</button>
      <aside className={`${styles.sidePanel} ${styles.rightPanel} ${drawer === "trace" ? styles.drawerOpen : ""}`} aria-label="Trace 摘要"><button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button><p className={styles.eyebrow}>Run Trace</p>{run ? <><p>状态：{run.status}</p><p>当前步骤：{run.current_step}</p><p>已完成步骤：{run.step_count}</p></> : <p>尚无执行事件</p>}{events.map((event) => <div className={styles.traceEvent} key={event.id}><code>#{event.id}</code><span>{event.type}</span><small>{event.step_id}</small></div>)}</aside>
      {drawer ? <button className={styles.backdrop} aria-label="关闭抽屉" type="button" onClick={closeDrawer} /> : null}
    </main>
  );
}
