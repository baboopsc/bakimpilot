/**
 * Tiny API client (D-027).
 *
 * - The access token lives only in this module's memory: never in
 *   localStorage, so injected scripts can't read it from storage.
 * - The refresh token is an httpOnly cookie the browser sends to
 *   /api/auth/refresh/ automatically; JavaScript never sees it.
 * - On a 401 we refresh once and retry the request. Concurrent 401s share
 *   one refresh call instead of stampeding the server.
 */

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionExpired: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function setSessionExpiredHandler(fn: (() => void) | null) {
  onSessionExpired = fn;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(ApiError.messageFrom(body, status));
  }

  /** Turn DRF error shapes ({detail}, {field: [msgs]}) into one readable line. */
  static messageFrom(body: unknown, status: number): string {
    if (body && typeof body === "object") {
      const b = body as Record<string, unknown>;
      if (typeof b.detail === "string") return b.detail;
      if (Array.isArray(b.detail)) return b.detail.join(" ");
      const parts = Object.entries(b).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" ") : String(v)}`);
      if (parts.length) return parts.join("; ");
    }
    return `Request failed (${status})`;
  }
}

export async function refreshAccessToken(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch("/api/auth/refresh/", { method: "POST", credentials: "same-origin" })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = (await res.json()) as { access: string };
        accessToken = data.access;
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

type Options = Omit<RequestInit, "body"> & { body?: unknown; retry?: boolean };

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const { body, retry = true, headers, ...rest } = opts;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const res = await fetch(path, {
    ...rest,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });

  if (res.status === 401 && retry && !path.startsWith("/api/auth/")) {
    if (await refreshAccessToken()) return api<T>(path, { ...opts, retry: false });
    onSessionExpired?.();
  }
  if (res.status === 204) return undefined as T;
  const data = res.headers.get("content-type")?.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

/** Build a query string, dropping empty values. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

/**
 * Open an uploaded manual at a page. A plain <a href> can't carry the
 * in-memory access token, so fetch the PDF with it, then open a blob URL.
 * `#page=N` is understood by the built-in PDF viewers of Chrome, Edge and Firefox.
 */
export async function openManual(documentId: number, page?: number) {
  const win = window.open("", "_blank"); // open synchronously so popup blockers allow it
  const get = () =>
    fetch(`/api/ai/documents/${documentId}/file/`, {
      credentials: "same-origin",
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    });
  let res = await get();
  if (res.status === 401 && (await refreshAccessToken())) res = await get();
  if (!res.ok) {
    win?.close();
    throw new ApiError(res.status, { detail: "Could not open the manual." });
  }
  const url = URL.createObjectURL(await res.blob());
  if (win) win.location.href = page ? `${url}#page=${page}` : url;
}
