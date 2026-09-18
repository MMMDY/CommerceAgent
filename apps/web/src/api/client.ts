export class ApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly detail?: unknown) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) {
    let detail: unknown;
    try { detail = await response.json(); } catch { /* preserve the HTTP status */ }
    const message = typeof detail === "object" && detail !== null && "detail" in detail
      ? String((detail as { detail: unknown }).detail)
      : `请求失败（${response.status}）`;
    throw new ApiError(response.status, message, detail);
  }
  return response.json() as Promise<T>;
}
