/** Selected files/folders and their index status. Nothing is copied or moved (FR-1). */
import { useState } from "react";
import { unwrap, useApi } from "@/api/client";
import { inTauri } from "@/api/connection";
import { useAction, useRoots, useSources } from "@/api/queries";
import { basename } from "@/lib/format";
import { selectSource, ui } from "@/state/selection";

async function pickPath(directory: boolean): Promise<string | null> {
  if (inTauri) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const res = await open({ directory, multiple: false });
    return typeof res === "string" ? res : null;
  }
  return window.prompt(directory ? "Folder path to add (read-only)" : "File path to add (read-only)");
}

const STATUS_TONE: Record<string, string> = { indexed: "verified", failed: "rejected", indexing: "proposed", pending: "proposed" };

export function SourcesPanel() {
  const { client } = useApi();
  const { data: roots } = useRoots();
  const { data: sources } = useSources();
  const [filter, setFilter] = useState("");
  const active = ui.use((s) => (s.selection.kind === "source" ? s.selection.id : null));

  const addRoot = useAction(async (directory: boolean) => {
    const path = await pickPath(directory);
    if (!path) return null;
    return unwrap(await client.POST("/api/roots", { body: { path, watch: true } }));
  }, "Added — indexing in the background");
  const removeRoot = useAction(async (id: string) => unwrap(await client.DELETE("/api/roots/{root_id}", { params: { path: { root_id: id } } })));
  const reindex = useAction(async (id: string) => unwrap(await client.POST("/api/sources/{source_id}/reindex", { params: { path: { source_id: id } } })), "Re-indexing");
  const forget = useAction(async (id: string) => {
    if (!window.confirm("Forget this file? Its chunks, embeddings and unverified claims are removed. Verified claims that relied only on it are flagged for review.")) return null;
    return unwrap(await client.POST("/api/sources/{source_id}/forget", { params: { path: { source_id: id } } }));
  }, "Forgotten");

  const shown = (sources ?? []).filter((s) => !filter || s.path.toLowerCase().includes(filter.toLowerCase()));
  return (
    <>
      <div className="section">
        <div className="row">
          <button type="button" className="btn small primary" onClick={() => addRoot.mutate(true)}>+ Folder</button>
          <button type="button" className="btn small" onClick={() => addRoot.mutate(false)}>+ File</button>
        </div>
        {(roots ?? []).map((r) => (
          <div key={r.id} className="row small" style={{ marginTop: 6 }}>
            <span title={r.watch ? "watched for changes" : ""}>{r.kind === "folder" ? "📁" : "📄"}</span>
            <span className="ellipsis" title={r.path}>{r.path}</span>
            <span className="spacer" />
            <button type="button" className="btn small icon" title="Stop tracking" onClick={() => removeRoot.mutate(r.id)}>×</button>
          </div>
        ))}
      </div>
      <div style={{ padding: "6px 10px" }}>
        <input className="input" style={{ width: "100%" }} placeholder={`Filter ${sources?.length ?? 0} files…`} value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="scroll">
        {shown.length === 0 && <div className="empty">Add a folder to start. Files stay where they are.</div>}
        {shown.map((s) => (
          <div key={s.id} className={`list-item ${active === s.id ? "active" : ""}`} onClick={() => selectSource(s.id)} title={s.error ?? s.path}>
            <span className="badge">{s.kind}</span>
            <span className="ellipsis" style={{ flex: 1 }}>{basename(s.path)}</span>
            <span className={`badge ${STATUS_TONE[s.status] ?? ""}`}>{s.status}</span>
            {active === s.id && (
              <>
                <button type="button" className="btn small icon" title="Re-index" onClick={(e) => { e.stopPropagation(); reindex.mutate(s.id); }}>↻</button>
                <button type="button" className="btn small icon bad" title="Forget this file" onClick={(e) => { e.stopPropagation(); forget.mutate(s.id); }}>⌫</button>
              </>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
