export const DEFAULT_AUTH_REDIRECT_PATH = "/monitors";

const PUBLIC_EXACT_PATHS = new Set(["/", "/sign-in", "/register"]);
const PUBLIC_PREFIXES = ["/explore"];
const PROTECTED_PREFIXES = ["/monitors", "/monitor", "/runs", "/events", "/account", "/alerts", "/jobs", "/admin"];

export function isProtectedRoute(pathname: string): boolean {
  if (!pathname) {
    return false;
  }

  if (PUBLIC_EXACT_PATHS.has(pathname)) {
    return false;
  }

  if (PUBLIC_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) {
    return false;
  }

  return PROTECTED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function buildCurrentPath(pathname: string, search: string | null | undefined): string {
  const normalizedPath = pathname?.startsWith("/") ? pathname : "/";
  if (!search) {
    return normalizedPath;
  }

  if (search.startsWith("?")) {
    return `${normalizedPath}${search}`;
  }

  return `${normalizedPath}?${search}`;
}

export function sanitizeNextPath(next: string | null | undefined): string {
  if (!next) {
    return DEFAULT_AUTH_REDIRECT_PATH;
  }

  const candidate = next.trim();
  if (!candidate.startsWith("/")) {
    return DEFAULT_AUTH_REDIRECT_PATH;
  }

  if (candidate.startsWith("//")) {
    return DEFAULT_AUTH_REDIRECT_PATH;
  }

  if (candidate.startsWith("/sign-in") || candidate.startsWith("/register")) {
    return DEFAULT_AUTH_REDIRECT_PATH;
  }

  return candidate;
}

export function buildSignInHref(nextPath: string, reason?: "expired" | "unauthenticated"): string {
  const searchParams = new URLSearchParams({ next: sanitizeNextPath(nextPath) });
  if (reason) {
    searchParams.set("reason", reason);
  }

  return `/sign-in?${searchParams.toString()}`;
}