import { describe, expect, it } from "vitest";

import { resolveRoute } from "./routes";

describe("resolveRoute", () => {
  it("maps the three Phase 0 routes", () => {
    expect(resolveRoute("/")).toBe("chat");
    expect(resolveRoute("/runs/demo")).toBe("run");
    expect(resolveRoute("/evals")).toBe("evals");
  });
});
