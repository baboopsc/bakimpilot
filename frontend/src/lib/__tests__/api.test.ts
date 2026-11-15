import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, qs, setAccessToken, setSessionExpiredHandler } from "../api";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("api client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("old-token");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setSessionExpiredHandler(null);
  });

  it("sends the bearer token and parses JSON", async () => {
    fetchMock.mockResolvedValueOnce(json(200, { ok: 1 }));
    expect(await api("/api/x/")).toEqual({ ok: 1 });
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer old-token");
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: "expired" }))
      .mockResolvedValueOnce(json(200, { access: "new-token" })) // /api/auth/refresh/
      .mockResolvedValueOnce(json(200, { data: 42 }));
    expect(await api("/api/x/")).toEqual({ data: 42 });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/auth/refresh/");
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe("Bearer new-token");
  });

  it("concurrent 401s share a single refresh call", async () => {
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (url === "/api/auth/refresh/") return json(200, { access: "fresh" });
      const auth = (init.headers as Record<string, string>).Authorization;
      return auth === "Bearer fresh" ? json(200, { url }) : json(401, {});
    });
    await Promise.all([api("/api/a/"), api("/api/b/"), api("/api/c/")]);
    expect(fetchMock.mock.calls.filter(([u]) => u === "/api/auth/refresh/")).toHaveLength(1);
  });

  it("calls the session-expired handler when refresh fails", async () => {
    const expired = vi.fn();
    setSessionExpiredHandler(expired);
    fetchMock.mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(401, {}));
    await expect(api("/api/x/")).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledOnce();
  });

  it("turns DRF errors into readable messages", async () => {
    fetchMock.mockResolvedValueOnce(json(400, { detail: "Checklist incomplete", code: "checklist_incomplete" }));
    await expect(api("/api/x/", { method: "POST", body: {} })).rejects.toThrow("Checklist incomplete");
    expect(ApiError.messageFrom({ quantity: ["Must be positive."] }, 400)).toBe("quantity: Must be positive.");
  });
});

describe("qs", () => {
  it("drops empty values", () => {
    expect(qs({ a: 1, b: "", c: undefined, d: null, e: "x y" })).toBe("?a=1&e=x+y");
    expect(qs({})).toBe("");
  });
});
