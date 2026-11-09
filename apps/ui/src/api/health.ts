import type { Connection } from "@folio/api-client";

/** A bounded authenticated request also detects an incorrect browser session token. */
export async function checkCore(conn: Connection, signal?: AbortSignal, authenticate = true): Promise<void> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(abort, 4000);
  try {
    const response = await fetch(`${conn.baseUrl}${authenticate ? "/api/status" : "/api/health"}`, {
      headers: authenticate ? { Authorization: `Bearer ${conn.token}` } : undefined, signal: controller.signal,
    });
    if (response.status === 401) throw new Error("The backend session token is incorrect. Restart Folio or check VITE_FOLIO_TOKEN.");
    if (!response.ok) throw new Error(`The backend returned HTTP ${response.status}. Check logs/core.log in Folio's data folder.`);
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
