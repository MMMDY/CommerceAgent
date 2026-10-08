import { describe, expect, it } from "vitest";

import { skillApprovalDetail, skillApprovalState, skillLifecycleSteps } from "./EvolutionLifecycle";

const baseSkill = {
  skill_id: "skill-1",
  scope_type: "tenant",
  scope_value: "demo-tenant",
  status: "PENDING_REVIEW",
  source_count: 5,
  cluster_key: "cluster-1",
  trigger: {},
  strategy: {},
  offline_gate_pass: true,
  safety_gate_pass: true,
  review_deadline: null,
  evaluation_gate_pass: true,
  evaluation_safety_result: "pass" as const,
  evaluation_judge_disagreement_count: 0,
  release_ids: [],
};

describe("Skill lifecycle flow projection", () => {
  it("keeps an unapproved candidate visibly stopped before release", () => {
    const steps = skillLifecycleSteps(baseSkill);
    expect(steps.map((step) => step.state)).toEqual([
      "flowPassed", "flowPassed", "flowPassed", "flowActive", "flowPendingBox",
    ]);
    expect(steps[3].detail).toContain("等待审批");
  });

  it("only shows the release stage as passed with an approved release association", () => {
    const steps = skillLifecycleSteps({ ...baseSkill, status: "ACTIVE", release_ids: ["release-1"] });
    expect(steps[3].state).toBe("flowPassed");
    expect(steps[4].state).toBe("flowPassed");
  });

  it("marks failed evidence or lifecycle states as blocked", () => {
    const steps = skillLifecycleSteps({ ...baseSkill, source_count: 2, status: "REJECTED", evaluation_gate_pass: false });
    expect(steps[0].state).toBe("flowBlocked");
    expect(steps[2].state).toBe("flowBlocked");
    expect(steps[3].state).toBe("flowBlocked");
    expect(steps[4].state).toBe("flowBlocked");
  });

  it("keeps rejected and unknown approval states out of the success tone", () => {
    expect(skillApprovalState("REJECTED")).toBe("flowBlocked");
    expect(skillApprovalDetail("REJECTED")).toContain("生命周期已停止");
    expect(skillApprovalState("FUTURE_BACKEND_STATE")).toBe("flowPendingBox");
    expect(skillApprovalDetail("FUTURE_BACKEND_STATE")).toContain("不推断为已批准");
  });
});
