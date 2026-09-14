const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const NON_REFRESHABLE_AUTH_PATHS = new Set(["/auth/login", "/auth/register", "/auth/refresh", "/auth/logout", "/auth/logout-all"]);
const DEFAULT_CSRF_COOKIE_NAME = "argus_csrf_token";

let refreshPromise: Promise<boolean> | null = null;

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit, allowRefresh = true): Promise<T> {
  const response = await executeRequest(path, init);

  if (response.status === 401 && allowRefresh && isRefreshEligiblePath(path)) {
    const refreshed = await tryRefreshSession();
    if (refreshed) {
      return apiRequest<T>(path, init, false);
    }
  }

  const text = await response.text();
  const body = text ? safeParseJson(text) : null;

  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("argus:auth-expired"));
    }

    throw new ApiError(response.status, extractApiErrorDetail(response.status, body));
  }

  return (body as T) ?? ({} as T);
}

export function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: "GET" });
}

export function apiPost<T>(path: string, payload?: unknown): Promise<T> {
  return apiRequest<T>(path, {
    method: "POST",
    body: payload == null ? undefined : JSON.stringify(payload),
  });
}

export function apiPatch<T>(path: string, payload: unknown): Promise<T> {
  return apiRequest<T>(path, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function apiDelete(path: string): Promise<void> {
  return apiRequest<void>(path, {
    method: "DELETE",
  });
}

export function extractApiErrorDetail(status: number, body: unknown): string {
  const fallback = `Request failed (${status})`;

  if (typeof body !== "object" || body == null || !Object.prototype.hasOwnProperty.call(body, "detail")) {
    return fallback;
  }

  const detail = (body as { detail: unknown }).detail;

  if (typeof detail === "string" && detail.trim().length > 0) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => {
        if (typeof entry === "string") {
          return entry;
        }
        if (typeof entry !== "object" || entry == null) {
          return null;
        }

        const record = entry as { loc?: unknown; msg?: unknown };
        const msg = typeof record.msg === "string" ? record.msg : null;
        const loc = Array.isArray(record.loc)
          ? record.loc
              .filter((segment): segment is string | number => typeof segment === "string" || typeof segment === "number")
              .filter((segment) => segment !== "body")
              .join(".")
          : "";

        if (!msg) {
          return null;
        }

        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter((value): value is string => Boolean(value));

    if (messages.length > 0) {
      return messages.join("; ");
    }
  }

  if (typeof detail === "object" && detail != null) {
    const record = detail as Record<string, unknown>;
    const code = typeof record.code === "string" ? record.code : null;

    if (code === "quota_exceeded") {
      const quota = typeof record.quota === "string" ? record.quota : "quota";
      const limit = typeof record.limit === "number" ? record.limit : null;
      const used = typeof record.used === "number" ? record.used : null;
      const labelMap: Record<string, string> = {
        max_monitors: "Monitor quota reached",
        max_active_monitors: "Active-monitor quota reached",
        max_aoi_area_km2: "AOI area quota exceeded",
        max_manual_runs_per_day: "Daily manual-run limit reached",
        max_observation_searches_per_day: "Daily observation-search limit reached",
        max_semantic_runs_per_day: "Daily semantic-analysis limit reached",
        max_concurrent_jobs: "Concurrent job limit reached",
      };
      const label = labelMap[quota] ?? quota.replaceAll("_", " ");
      if (limit != null && used != null) {
        return `${label} (${used}/${limit}).`;
      }
      return label;
    }

    if (code === "rate_limited") {
      const scope = typeof record.scope === "string" ? record.scope : "request";
      const retryAfter = typeof record.retry_after_seconds === "number" ? record.retry_after_seconds : null;
      if (retryAfter != null) {
        return `Rate limit exceeded for ${scope}. Retry in ${retryAfter}s.`;
      }
      return `Rate limit exceeded for ${scope}.`;
    }

    if (typeof record.msg === "string") {
      return record.msg;
    }
  }

  return fallback;
}

function safeParseJson(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

async function executeRequest(path: string, init?: RequestInit): Promise<Response> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers ?? {});

  if (!headers.has("Content-Type") && (method !== "GET" && method !== "HEAD")) {
    headers.set("Content-Type", "application/json");
  }

  if (!SAFE_METHODS.has(method) && !headers.has("x-argus-csrf-token")) {
    const csrf = readCookie(DEFAULT_CSRF_COOKIE_NAME);
    if (csrf) {
      headers.set("x-argus-csrf-token", csrf);
    }
  }

  return fetch(`/api/backend${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
    cache: "no-store",
  });
}

function isRefreshEligiblePath(path: string): boolean {
  const normalized = path.split("?", 1)[0];
  return !NON_REFRESHABLE_AUTH_PATHS.has(normalized);
}

async function tryRefreshSession(): Promise<boolean> {
  if (refreshPromise != null) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    const csrf = readCookie(DEFAULT_CSRF_COOKIE_NAME);
    if (!csrf) {
      return false;
    }

    try {
      const response = await fetch("/api/backend/auth/refresh", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-argus-csrf-token": csrf,
        },
        credentials: "include",
        cache: "no-store",
      });

      return response.ok;
    } catch {
      return false;
    }
  })();

  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }

  const target = `${name}=`;
  const parts = document.cookie.split(";");
  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed.startsWith(target)) {
      continue;
    }
    return decodeURIComponent(trimmed.slice(target.length));
  }

  return null;
}
