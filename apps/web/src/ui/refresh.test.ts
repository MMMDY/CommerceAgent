import { describe, expect, it } from "vitest";

import { RELEASE_STATUS_REFRESH_MS, releaseStatusRefreshWithinSlo } from "./refresh";

describe("release status refresh", () => {
  it("polls no slower than the one-minute stop propagation target", () => {
    expect(RELEASE_STATUS_REFRESH_MS).toBe(15_000);
    expect(releaseStatusRefreshWithinSlo()).toBe(true);
  });
});
