import { useMemo, useState } from "react";

import styles from "../styles/App.module.css";
import type { EventItem } from "../contracts";

const eventLabels: Record<string, string> = {
  run_created: "Run 已创建", safety_routed: "Safety Router 完成", model_request_started: "模型调用开始",
  model_request_succeeded: "模型调用完成", model_request_failed: "模型调用失败", decision_validation_failed: "决策校验失败",
  recovery_attempt_started: "恢复尝试开始", recovery_attempt_succeeded: "恢复尝试完成", recovery_attempt_failed: "恢复尝试失败",
  tool_request_started: "工具调用开始", tool_request_succeeded: "工具调用完成", tool_request_failed: "工具调用失败",
  tool_called: "工具已调用", tool_observed: "工具结果已观测", assistant_response: "Agent 生成回复",
  terminal_response_published: "回复已发布", step_completed: "编排步骤完成", waiting_for_user: "等待用户补充",
  handoff_resolved: "人工处理完成", handoff_created: "已创建人工工单", skill_matched: "经验 Skill 命中",
  release_assigned: "发布版本已分配", routing_completed: "路由识别完成", routing_shadow_compared: "Router Shadow 对比完成",
  intent_classified: "意图识别完成", policy_selected: "响应策略已选择", rag_retrieval_started: "RAG 检索开始",
  rag_retrieval_succeeded: "RAG 检索完成", guardrail_passed: "Guardrail 校验通过", guardrail_blocked: "Guardrail 已阻断",
  fallback_activated: "安全兜底已启用", mutation_prepared: "操作预览已生成", user_confirmed: "用户已确认",
  commit_started: "业务提交开始", commit_observed: "业务提交结果已观测", state_verified: "状态校验完成",
  mutation_uncertain: "业务状态不确定", terminal_response_publish_failed: "回复发布失败", failed: "Run 失败",
};

const processStages = ["受理", "识别与路由", "Agent 执行", "Guardrail", "上线与成本", "回复发布"] as const;
type ProcessStage = (typeof processStages)[number];

export function eventLabel(type: string): string { return eventLabels[type] ?? type; }

export function eventStage(type: string, payload: Record<string, unknown> = {}): string {
  if (type === "run_created") return "受理";
  if (type === "release_assigned") return "上线与成本";
  if (type === "rag_retrieval_started" || type === "rag_retrieval_succeeded") return "Agent 执行";
  if (type === "guardrail_passed" || type === "guardrail_blocked" || type === "fallback_activated") return "Guardrail";
  if (type.includes("safety") || type.includes("routing") || type === "intent_classified" || (type.startsWith("model_request") && payload.purpose === "routing")) return "识别与路由";
  if (type.startsWith("tool_") || type === "tool_called" || type === "tool_observed" || type.includes("model_request")) return "Agent 执行";
  if (type.includes("mutation") || type.includes("commit") || type.includes("verified") || type.includes("handoff") || type.includes("decision")) return "Guardrail";
  if (type.includes("response") || type === "assistant_response") return "回复发布";
  return "Agent 执行";
}

export function safeEventDetails(payload: Record<string, unknown>): string {
  const allowedKeys = [
    "purpose", "outcome", "status", "error_code", "reason_code", "disposition", "risk_level", "domain", "category", "intent", "request_domain", "request_risk_level", "response_policy", "execution_mode", "alternative_count", "confidence", "domain_confidence", "risk_confidence", "confidence_calibration_version", "tool", "current_router", "shadow_router", "current_outcome", "current_reason_code", "current_intent", "current_response_policy", "shadow_outcome", "shadow_reason_code", "shadow_intent", "shadow_response_policy", "different", "shadow_is_observation_only", "current_route", "candidate_route", "current_skill", "candidate_skill", "candidate_runtime_available", "candidate_execution_allowed", "observation_only", "estimated_cost_delta_microusd", "attempt_no", "character_count", "retryable", "fallback_used", "ticket_id", "mode", "selected_version", "traffic_percent", "bucket",
  ];
  const safe = Object.fromEntries(allowedKeys.filter((key) => key in payload).map((key) => [key, payload[key]]));
  if (Object.keys(safe).length === 0) return "仅展示事件类型与步骤，详细参数已隐藏";
  return Object.entries(safe).map(([key, value]) => `${key}=${String(value)}`).join(" · ");
}

function eventTone(type: string): "success" | "warning" | "danger" | "neutral" {
  if (type.includes("failed") || type === "failed" || type === "decision_validation_failed") return "danger";
  if (type === "safety_routed" || type === "waiting_for_user" || type === "handoff_created") return "warning";
  if (type.includes("succeeded") || type.includes("completed") || type.includes("published") || type.includes("observed")) return "success";
  return "neutral";
}

export function elapsedLabel(previous: EventItem | undefined, current: EventItem): string {
  if (!previous?.occurred_at || !current.occurred_at) return "";
  const elapsed = new Date(current.occurred_at).getTime() - new Date(previous.occurred_at).getTime();
  if (!Number.isFinite(elapsed) || elapsed < 0) return "";
  return elapsed < 1000 ? `+${elapsed} ms` : `+${(elapsed / 1000).toFixed(2)} s`;
}

export function EventTimeline({ events }: { events: EventItem[] }) {
  const [selectedStage, setSelectedStage] = useState<ProcessStage | "all">("all");
  const stageCounts = processStages.map((stage) => ({ stage, count: events.filter((event) => eventStage(event.type, event.payload) === stage).length }));
  const visible = useMemo(() => {
    const filtered = selectedStage === "all"
      ? events
      : events.filter((event) => eventStage(event.type, event.payload) === selectedStage);
    return filtered.slice(-12);
  }, [events, selectedStage]);
  const eventIndexes = useMemo(() => new Map(events.map((event, index) => [event.id, index])), [events]);
  return <section className={styles.eventStrip} aria-label="Agent 事件时间轴">
    <div className={styles.eventStripHeader}><div><p className={styles.eyebrow}>Event Timeline</p><h3>实时执行里程碑</h3></div><span>{events.length} 个事件</span></div>
    <div className={styles.milestoneFlow} aria-label="Agent 阶段事件计数">
      <button className={`${styles.milestoneItem} ${selectedStage === "all" ? styles.milestoneSelected : ""}`} type="button" onClick={() => setSelectedStage("all")} aria-pressed={selectedStage === "all"}><span>{events.length || "–"}</span><strong>全部</strong></button>
      {stageCounts.map(({ stage, count }, index) => <div className={styles.milestoneItemWrap} key={stage}><button className={`${styles.milestoneItem} ${selectedStage === stage ? styles.milestoneSelected : ""}`} type="button" onClick={() => setSelectedStage(stage)} aria-pressed={selectedStage === stage}><span className={count > 0 ? styles.milestoneActive : ""}>{count > 0 ? count : "–"}</span><strong>{stage}</strong></button>{index < stageCounts.length - 1 ? <i aria-hidden="true">→</i> : null}</div>)}
    </div>
    <p className={styles.timelineFilterNote}>{selectedStage === "all" ? "按真实写入顺序展示最近 12 条事件。" : `当前查看“${selectedStage}”阶段，共 ${stageCounts.find((item) => item.stage === selectedStage)?.count ?? 0} 条事件。`} <span>点击阶段可筛选</span></p>
    {visible.length === 0 ? <p className={styles.empty}>请求启动后，这里会按时间展示路由、模型、工具和回复事件。</p> : <ol className={styles.eventRail}>{visible.map((event) => { const tone = eventTone(event.type); const eventIndex = eventIndexes.get(event.id); const previous = eventIndex === undefined ? undefined : events[eventIndex - 1]; const elapsed = elapsedLabel(previous, event); return <li className={styles.eventRailItem} key={event.id}><span className={`${styles.eventRailMarker} ${styles[`eventRail${tone[0].toUpperCase()}${tone.slice(1)}`] ?? ""}`} aria-hidden="true" /><div><strong>{eventLabel(event.type)}</strong><small>{event.step_id}{event.occurred_at ? ` · ${new Date(event.occurred_at).toLocaleTimeString()}` : ""}{elapsed ? ` · ${elapsed}` : ""}</small></div></li>; })}</ol>}
  </section>;
}
