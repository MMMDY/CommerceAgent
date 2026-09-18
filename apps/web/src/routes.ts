export type RouteKind =
  | "chat"
  | "run"
  | "evals"
  | "operations"
  | "failures"
  | "failure"
  | "skills"
  | "skill"
  | "releases"
  | "release"
  | "not_found";

export function resolveRoute(pathname: string): RouteKind {
  if (pathname === "/") return "chat";
  if (pathname === "/evals" || /^\/evals\/[^/]+$/.test(pathname)) return "evals";
  if (/^\/runs\/[^/]+$/.test(pathname)) return "run";
  if (pathname === "/operations") return "operations";
  if (pathname === "/failures") return "failures";
  if (/^\/failures\/[^/]+$/.test(pathname)) return "failure";
  if (pathname === "/skills") return "skills";
  if (/^\/skills\/[^/]+$/.test(pathname)) return "skill";
  if (pathname === "/releases") return "releases";
  if (/^\/releases\/[^/]+$/.test(pathname)) return "release";
  return "not_found";
}
