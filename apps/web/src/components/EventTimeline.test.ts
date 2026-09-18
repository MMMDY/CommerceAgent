import { describe, expect, it } from "vitest";

import { elapsedLabel, eventLabel, eventStage, safeEventDetails } from "./EventTimeline";

describe("EventTimeline projection", () => {
  it("maps execution events to the visible Agent stages", () => {
    expect(eventStage("run_created")).toBe("受理");
    expect(eventStage("intent_classified")).toBe("识别与路由");
    expect(eventStage("model_request_succeeded", { purpose: "routing" })).toBe("识别与路由");
    expect(eventStage("rag_retrieval_succeeded")).toBe("Agent 执行");
    expect(eventStage("guardrail_blocked")).toBe("Guardrail");
    expect(eventStage("terminal_response_published")).toBe("回复发布");
  });

  it("keeps labels readable and event details on the allowlist", () => {
    expect(eventLabel("safety_routed")).toBe("Safety Router 完成");
    expect(eventLabel("unknown_event")).toBe("unknown_event");
    expect(safeEventDetails({ status: "ok", prompt: "must not render", tool_args: { secret: "x" } }))
      .toBe("status=ok");
    expect(safeEventDetails({ prompt: "must not render" })).toContain("详细参数已隐藏");
  });

  it("shows only measured positive gaps between adjacent events", () => {
    expect(elapsedLabel({ id: 1, type: "run_created", step_id: "a", payload: {}, occurred_at: "2026-09-18T00:00:00.000Z" }, { id: 2, type: "step_completed", step_id: "b", payload: {}, occurred_at: "2026-09-18T00:00:00.250Z" })).toBe("+250 ms");
    expect(elapsedLabel(undefined, { id: 2, type: "step_completed", step_id: "b", payload: {}, occurred_at: "2026-09-18T00:00:00.250Z" })).toBe("");
    expect(elapsedLabel({ id: 2, type: "step_completed", step_id: "b", payload: {}, occurred_at: "2026-09-18T00:00:01.000Z" }, { id: 1, type: "run_created", step_id: "a", payload: {}, occurred_at: "2026-09-18T00:00:00.000Z" })).toBe("");
  });

  it("can measure a filtered event against its real predecessor", () => {
    const events = [
      { id: 1, type: "run_created", step_id: "intake", payload: {}, occurred_at: "2026-09-18T10:00:00.000Z" },
      { id: 2, type: "model_request_succeeded", step_id: "routing", payload: { purpose: "routing" }, occurred_at: "2026-09-18T10:00:01.000Z" },
      { id: 3, type: "assistant_response", step_id: "publish", payload: {}, occurred_at: "2026-09-18T10:00:03.500Z" },
    ];
    expect(elapsedLabel(events[1], events[2])).toBe("+2.50 s");
  });
});
