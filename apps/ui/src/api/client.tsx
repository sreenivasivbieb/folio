import { type Connection, createFolioClient, type FolioClient } from "@folio/api-client";
import { createContext, type ReactNode, useContext, useMemo } from "react";

interface Api {
  conn: Connection;
  client: FolioClient;
}

const ApiContext = createContext<Api | null>(null);

export function ApiProvider({ conn, children }: { conn: Connection; children: ReactNode }) {
  const value = useMemo(() => ({ conn, client: createFolioClient(conn) }), [conn]);
  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  const api = useContext(ApiContext);
  if (!api) throw new Error("useApi outside ApiProvider");
  return api;
}

/** Unwrap an openapi-fetch result: return data or throw the core's error detail. */
export function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.error !== undefined || res.data === undefined) {
    const detail = (res.error as { detail?: unknown } | undefined)?.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.response.status})`);
  }
  return res.data;
}
