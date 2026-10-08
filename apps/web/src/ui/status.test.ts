import { describe, expect, it } from "vitest";

import { statusLabel, statusTone } from "./status";

describe("status projection", () => {
  it("keeps successful lifecycle states green", () => {
    expect(statusTone("ACTIVE")).toBe("success");
    expect(statusTone("completed")).toBe("success");
  });

  it("does not present pending or unknown states as success", () => {
    expect(statusTone("PENDING_REVIEW")).toBe("warning");
    expect(statusTone("CANARY")).toBe("warning");
    expect(statusTone("running_workflow")).toBe("warning");
    expect(statusTone("routing")).toBe("warning");
    expect(statusTone("future_backend_state")).toBe("neutral");
    expect(statusTone(undefined)).toBe("neutral");
  });

  it("marks terminal failures as dangerous", () => {
    expect(statusTone("ROLLED_BACK")).toBe("danger");
    expect(statusTone("failed")).toBe("danger");
  });

  it("projects known lifecycle labels without making unknown values look successful", () => {
    expect(statusLabel("PENDING_REVIEW")).toBe("待人工审批");
    expect(statusLabel("running_workflow")).toBe("流程执行中");
    expect(statusLabel("waiting_human")).toBe("待人工处理");
    expect(statusLabel("future_backend_state")).toBe("future_backend_state");
  });
});
