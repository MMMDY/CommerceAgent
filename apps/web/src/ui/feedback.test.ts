import { describe, expect, it } from "vitest";

import { buildFeedbackRequest } from "./feedback";

describe("buildFeedbackRequest", () => {
  it("does not send correction text without explicit consent", () => {
    const request = buildFeedbackRequest({
      rating: "down",
      reasonCodes: ["response_inaccurate"],
      correction: "包含原始用户信息的纠错文本",
      consent: false,
      idempotencyKey: "feedback-1",
    });

    expect(request).toEqual({
      rating: "down",
      reason_codes: ["response_inaccurate"],
      consent_for_improvement: false,
      idempotency_key: "feedback-1",
    });
    expect("correction" in request).toBe(false);
  });

  it("trims and sends correction only after consent", () => {
    expect(buildFeedbackRequest({
      rating: "down",
      correction: "  脱敏后的建议  ",
      consent: true,
      idempotencyKey: "feedback-2",
    })).toEqual({
      rating: "down",
      reason_codes: [],
      correction: "脱敏后的建议",
      consent_for_improvement: true,
      idempotency_key: "feedback-2",
    });
  });
});
