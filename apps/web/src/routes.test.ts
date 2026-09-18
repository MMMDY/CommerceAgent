import { describe, expect, it } from "vitest";

import { resolveRoute } from "./routes";

describe("resolveRoute", () => {
  it("maps the three Phase 0 routes", () => {
    expect(resolveRoute("/")).toBe("chat");
    expect(resolveRoute("/runs/demo")).toBe("run");
    expect(resolveRoute("/evals")).toBe("evals");
  });

  it("reserves the control-plane routes for later phases", () => {
    expect(resolveRoute("/operations")).toBe("operations");
    expect(resolveRoute("/failures")).toBe("failures");
    expect(resolveRoute("/failures/failure-1")).toBe("failure");
    expect(resolveRoute("/skills")).toBe("skills");
    expect(resolveRoute("/skills/skill-1")).toBe("skill");
    expect(resolveRoute("/releases")).toBe("releases");
    expect(resolveRoute("/releases/release-1")).toBe("release");
    expect(resolveRoute("/evals/eval-1")).toBe("evals");
  });

  it("fails closed for malformed resource paths and unknown pages", () => {
    expect(resolveRoute("/runs/")).toBe("not_found");
    expect(resolveRoute("/skills/")).toBe("not_found");
    expect(resolveRoute("/unknown")).toBe("not_found");
  });
});
