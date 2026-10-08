import { describe, expect, it } from "vitest";

import { flowDurationLabel, flowNodeState } from "./AgentFlow";

describe("AgentFlow timing projection", () => {
  it("uses the measured event envelope for the visible flow header", () => {
    const events = [
      { id: 1, type: "run_created", payload: {}, occurred_at: "2026-09-18T10:00:00.000Z" },
      { id: 2, type: "terminal_response_published", payload: {}, occurred_at: "2026-09-18T10:00:01.250Z" },
    ];
    expect(flowDurationLabel(events)).toBe("1.25 s");
  });

  it("does not invent a duration when timestamps are missing or insufficient", () => {
    expect(flowDurationLabel([{ type: "run_created", payload: {} }])).toBe("N/A");
    expect(flowDurationLabel([
      { type: "run_created", payload: {}, occurred_at: "not-a-date" },
      { type: "terminal_response_published", payload: {}, occurred_at: "2026-09-18T10:00:01.250Z" },
    ])).toBe("N/A");
  });
});

describe("AgentFlow evidence projection", () => {
  const completed = { status: "completed", current_step: "terminal", step_count: 3 } as const;

  it("does not turn a terminal status into completed nodes without events", () => {
    expect(flowNodeState(completed, [], "intake")).toBe("na");
    expect(flowNodeState(completed, [], "safety")).toBe("na");
    expect(flowNodeState(completed, [], "executor")).toBe("na");
    expect(flowNodeState(completed, [], "response")).toBe("pending");
  });

  it("marks only stages supported by the event path", () => {
    const events = [
      { type: "run_created", payload: {} },
      { type: "safety_routed", payload: { risk_level: "low" } },
      { type: "model_request_succeeded", payload: { purpose: "routing" } },
      { type: "step_completed", payload: { response_policy: "execute" } },
      { type: "model_request_succeeded", payload: { purpose: "agent" } },
      { type: "guardrail_passed", payload: {} },
      { type: "terminal_response_published", payload: {} },
    ];
    expect(flowNodeState(completed, events, "safety")).toBe("done");
    expect(flowNodeState(completed, events, "intake")).toBe("done");
    expect(flowNodeState(completed, events, "domain")).toBe("done");
    expect(flowNodeState(completed, events, "intent")).toBe("done");
    expect(flowNodeState(completed, events, "policy")).toBe("done");
    expect(flowNodeState(completed, events, "executor")).toBe("done");
    expect(flowNodeState(completed, events, "guard")).toBe("done");
    expect(flowNodeState(completed, events, "response")).toBe("done");
  });
});
