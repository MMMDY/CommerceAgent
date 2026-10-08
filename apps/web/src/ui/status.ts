export type StatusTone = "success" | "warning" | "danger" | "neutral";

const successStatuses = new Set(["approved", "active", "completed", "full", "measured", "pass", "passed", "success", "succeeded", "verified_success"]);
const warningStatuses = new Set(["candidate", "canary", "canary_5", "canary_25", "canary_50", "created", "high", "incomplete", "medium", "pending", "pending_review", "queued", "routing", "running", "running_readonly", "running_workflow", "shadow", "waiting_confirmation", "waiting_human", "waiting_user", "committing", "verifying"]);
const dangerStatuses = new Set(["blocked", "cancelled", "error", "expired", "fail", "failed", "rejected", "rolled_back", "stopped", "timeout", "unavailable", "verified_failure"]);

const knownLabels: Record<string, string> = {
  active: "生产中",
  approved: "已批准",
  cancelled: "已取消",
  canary: "Canary",
  canary_5: "Canary 5%",
  canary_25: "Canary 25%",
  canary_50: "Canary 50%",
  candidate: "候选",
  completed: "已完成",
  committing: "提交中",
  created: "已创建",
  error: "错误",
  expired: "已过期",
  failed: "失败",
  full: "100%",
  incomplete: "证据不完整",
  pass: "通过",
  passed: "通过",
  pending_review: "待人工审批",
  rejected: "已拒绝",
  rolled_back: "已回滚",
  routing: "路由中",
  running: "运行中",
  running_readonly: "只读执行中",
  running_workflow: "流程执行中",
  shadow: "Shadow",
  stopped: "已停止",
  timeout: "超时",
  unavailable: "不可用",
  verified_failure: "人工确认失败",
  verified_success: "人工确认成功",
  verifying: "校验中",
  waiting_confirmation: "待用户确认",
  waiting_human: "待人工处理",
  waiting_user: "待用户补充",
};

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
  const raw = String(value);
  return knownLabels[raw.trim().toLowerCase()] ?? raw;
}
