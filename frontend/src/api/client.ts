export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  const text = await response.text();
  const body = text ? safeParseJson(text) : null;

  if (!response.ok) {
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

  if (typeof detail === "object" && detail != null && "msg" in detail && typeof (detail as { msg?: unknown }).msg === "string") {
    return (detail as { msg: string }).msg;
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
