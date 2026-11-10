/**
 * Typed client for the Folio core service.
 *
 * `schema.d.ts` is GENERATED from the core's OpenAPI spec (`npm run gen:client`); never edit it
 * by hand. CI regenerates it and fails if the committed copy is stale, so the UI and the core
 * cannot drift apart silently.
 */
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type { components, paths };
type S = components["schemas"];

export type Entity = S["Entity"];
export type Claim = S["Claim"];
export type Evidence = S["Evidence"];
export type Locator = S["Locator"];
export type Source = S["Source"];
export type Chunk = S["Chunk"];
export type Label = S["Label"];
export type Job = S["Job"];
export type EntityCard = S["EntityCard"];
export type ClaimInCard = S["ClaimInCard"];
export type GraphView = S["GraphView"];
export type TimelineView = S["TimelineView"];
export type SwimlaneView = S["SwimlaneView"];
export type ReviewView = S["ReviewView"];
export type SearchResult = S["SearchResult"];
export type Passage = S["Passage"];
export type Status = S["Status"];
export type SchemaView = S["SchemaView"];
export type HistoryEntry = S["HistoryEntry"];
export type GroupEntry = S["GroupEntry"];
export type EntityNode = S["EntityNode"];
export type Drop = S["Drop"];
export type DiskPreview = S["DiskPreview"];

export interface Connection {
  baseUrl: string;
  token: string;
}

export function createFolioClient(conn: Connection) {
  return createClient<paths>({
    baseUrl: conn.baseUrl,
    headers: { Authorization: `Bearer ${conn.token}` },
  });
}

export type FolioClient = ReturnType<typeof createFolioClient>;

/** URL for elements that cannot send headers (EventSource, <video>, <img>, pdf.js). */
export function authedUrl(conn: Connection, path: string): string {
  const sep = path.includes("?") ? "&" : "?";
  return `${conn.baseUrl}${path}${sep}token=${encodeURIComponent(conn.token)}`;
}
