export type StatusTone = "success" | "warning" | "danger" | "neutral";

const successStatuses = new Set(["approved", "active", "completed", "full", "pass", "passed", "verified_success"]);
const warningStatuses = new Set(["candidate", "canary", "canary_5", "canary_25", "canary_50", "incomplete", "pending_review", "shadow", "waiting_confirmation", "waiting_human", "waiting_user"]);
const dangerStatuses = new Set(["blocked", "expired", "fail", "failed", "rejected", "rolled_back", "stopped", "verified_failure"]);

function normalized(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

/** Unknown values deliberately stay neutral; they must never look like a successful state. */
export function statusTone(value: unknown): StatusTone {
  const status = normalized(value);
  if (successStatuses.has(status)) return "success";
  if (warningStatuses.has(status)) return "warning";
  if (dangerStatuses.has(status)) return "danger";
  return "neutral";
}

export function statusLabel(value: unknown, fallback = "N/A"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}
