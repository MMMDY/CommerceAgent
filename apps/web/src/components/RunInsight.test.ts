import { describe, expect, it } from "vitest";

import { relatedIds } from "./RunInsight";

describe("RunInsight related evidence projection", () => {
  it("only links IDs explicitly present on the matching event types", () => {
    const events = [
      { type: "release_assigned", payload: { release_id: "release-1", skill_id: "skill-1" } },
      { type: "skill_matched", payload: { skill_id: "skill-1" } },
      { type: "failed", payload: { release_id: "must-not-link" } },
    ];
    expect(relatedIds(events, ["release_assigned"], ["release_id"])).toEqual(["release-1"]);
    expect(relatedIds(events, ["skill_matched"], ["skill_id"])).toEqual(["skill-1"]);
  });

  it("deduplicates repeated event references and ignores empty values", () => {
    const events = [
      { type: "skill_matched", payload: { skill_id: "skill-1" } },
      { type: "skill_matched", payload: { skill_id: "skill-1" } },
      { type: "skill_matched", payload: { skill_id: "" } },
    ];
    expect(relatedIds(events, ["skill_matched"], ["skill_id"])).toEqual(["skill-1"]);
  });
});
