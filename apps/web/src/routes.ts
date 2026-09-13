export type RouteKind = "chat" | "run" | "evals";

export function resolveRoute(pathname: string): RouteKind {
  if (pathname === "/evals") {
    return "evals";
  }
  if (pathname.startsWith("/runs/")) {
    return "run";
  }
  return "chat";
}
