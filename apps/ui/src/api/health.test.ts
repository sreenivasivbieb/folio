import { afterEach, describe, expect, it, vi } from "vitest";
import { checkCore } from "./health";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const conn = { baseUrl: "http://127.0.0.1:8765", token: "fixture-token" };

describe("backend readiness", () => {
  it("uses the lightweight liveness endpoint after authenticating", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetch);
    await checkCore(conn, undefined, false);
    expect(fetch.mock.calls[0][0]).toBe("http://127.0.0.1:8765/api/health");
  });
  it("authenticates instead of accepting an unrelated healthy backend", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    vi.stubGlobal("fetch", fetch);
    await expect(checkCore(conn)).rejects.toThrow("session token");
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe("Bearer fixture-token");
  });
  it("reports backend failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    await expect(checkCore(conn)).rejects.toThrow("HTTP 503");
  });
  it("bounds requests that never respond", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new DOMException("Timed out", "AbortError")));
    })));
    const assertion = expect(checkCore(conn)).rejects.toThrow("Timed out");
    await vi.advanceTimersByTimeAsync(4001);
    await assertion;
  });
});
