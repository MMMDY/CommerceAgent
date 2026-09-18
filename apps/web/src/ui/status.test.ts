import { describe, expect, it } from "vitest";

import { statusTone } from "./status";

describe("status projection", () => {
  it("keeps successful lifecycle states green", () => {
    expect(statusTone("ACTIVE")).toBe("success");
    expect(statusTone("completed")).toBe("success");
  });

  it("does not present pending or unknown states as success", () => {
    expect(statusTone("PENDING_REVIEW")).toBe("warning");
    expect(statusTone("CANARY")).toBe("warning");
    expect(statusTone("future_backend_state")).toBe("neutral");
    expect(statusTone(undefined)).toBe("neutral");
  });

  it("marks terminal failures as dangerous", () => {
    expect(statusTone("ROLLED_BACK")).toBe("danger");
    expect(statusTone("failed")).toBe("danger");
  });
});
