export type FeedbackRating = "up" | "down";

export type FeedbackRequest = {
  rating: FeedbackRating;
  reason_codes: string[];
  correction?: string;
  consent_for_improvement: boolean;
  idempotency_key: string;
};

export function buildFeedbackRequest(input: {
  rating: FeedbackRating;
  reasonCodes?: string[];
  correction?: string;
  consent: boolean;
  idempotencyKey: string;
}): FeedbackRequest {
  const correction = input.correction?.trim();
  const allowedCorrection = Boolean(input.consent && correction);
  return {
    rating: input.rating,
    reason_codes: input.reasonCodes ?? [],
    ...(allowedCorrection ? { correction } : {}),
    consent_for_improvement: allowedCorrection,
    idempotency_key: input.idempotencyKey,
  };
}
