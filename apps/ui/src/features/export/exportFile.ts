/** Export (FR-9): JSON and GraphML are lossless round trips; Markdown and CSV are for people. */
import type { Connection } from "@folio/api-client";
import { inTauri } from "@/api/connection";

export const EXPORT_FORMATS = [
  { id: "json", file: "folio-export.json", title: "JSON", text: "Everything, including full history. Re-importable." },
  { id: "graphml", file: "folio-graph.graphml", title: "GraphML", text: "The graph with provenance — opens in Gephi or yEd." },
  { id: "markdown", file: "folio-export.md", title: "Markdown", text: "Readable notes, one section per entity." },
  { id: "csv", file: "folio-export-csv.zip", title: "CSV", text: "Entities, aliases, claims and evidence tables." },
] as const;

export type ExportFormat = (typeof EXPORT_FORMATS)[number];

/** Returns false when the user cancelled the save dialog. */
export async function exportFile(conn: Connection, fmt: ExportFormat): Promise<boolean> {
  const res = await fetch(`${conn.baseUrl}/api/export/${fmt.id}`, { headers: { Authorization: `Bearer ${conn.token}` } });
  if (!res.ok) throw new Error(`export failed (${res.status})`);
  const bytes = new Uint8Array(await res.arrayBuffer());
  if (inTauri) {
    const { save } = await import("@tauri-apps/plugin-dialog");
    const { invoke } = await import("@tauri-apps/api/core");
    const path = await save({ defaultPath: fmt.file });
    if (!path) return false;
    // Raw IPC body: the bytes go through as-is (a number array would use ~8x the memory).
    await invoke("save_file", bytes, { headers: { "x-folio-path": encodeURIComponent(path) } });
    return true;
  }
  const url = URL.createObjectURL(new Blob([bytes]));
  Object.assign(document.createElement("a"), { href: url, download: fmt.file }).click();
  URL.revokeObjectURL(url);
  return true;
}
