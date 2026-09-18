export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sequence_no: number;
  run_id: string | null;
};

export type Conversation = { id: string; status: string };
export type Preview = {
  mutation_type: string;
  resource_ref: string;
  operation: string;
  summary: string;
  impact: Record<string, unknown>;
  amount: { value: number; currency: string };
  channel: string;
  estimated_time: string;
  policy_version: string;
};
export type Run = {
  run_id: string;
  conversation_id?: string;
  status: string;
  status_label?: string;
  status_description?: string;
  current_step: string;
  step_count: number;
  execution_mode?: string;
  workflow_id?: string | null;
  workflow_version?: string | null;
  allowed_actions?: string[];
  retryable?: boolean;
  preview?: Preview | null;
  confirmation_expires_at?: string | null;
  token_refresh_required?: boolean;
};
export type EventItem = {
  id: number;
  type: string;
  step_id: string;
  payload: Record<string, unknown>;
  occurred_at?: string;
};
export type StateNode = {
  status: string;
  label: string;
  description: string;
  terminal: boolean;
  transitions: string[];
};
export type Evidence = {
  evidence_id: string;
  source_uri: string;
  version: string;
  excerpt: string;
};
export type HumanReview = {
  ticket_id: string;
  run_id: string;
  status: string;
  reason_code: string;
  operation?: string | null;
  details: Record<string, unknown>;
  created_at: string;
  resolved_at?: string | null;
  resolution?: string | null;
};
export type Scenario = { id: string; label: string; prompt: string };
