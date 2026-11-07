/**
 * Where the core service is and how to authenticate.
 *
 * Inside the desktop shell, the Rust side starts the core sidecar on a random localhost port with
 * a fresh per-session token and hands both over via the `core_connection` command. In plain
 * browser development we read them from Vite env (see .env.development).
 */
import type { Connection } from "@folio/api-client";

export const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function resolveConnection(): Promise<Connection> {
  if (inTauri) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<Connection>("core_connection");
  }
  const params = new URLSearchParams(window.location.search);
  return {
    baseUrl: params.get("core") ?? import.meta.env.VITE_FOLIO_URL ?? "http://127.0.0.1:8765",
    token: params.get("token") ?? import.meta.env.VITE_FOLIO_TOKEN ?? "dev",
  };
}
