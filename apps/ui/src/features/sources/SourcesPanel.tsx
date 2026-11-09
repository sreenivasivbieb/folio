/** Library: selected files/folders and their index status. Nothing is copied or moved (FR-1). */
import type { Source } from "@folio/api-client";
import { useState } from "react";
import { unwrap, useApi } from "@/api/client";
import { inTauri } from "@/api/connection";
import { useAction, useFilePage, useJobs, useRoots } from "@/api/queries";
import { Icon, kindIcon } from "@/components/Icon";
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

export function useAddRoot() {
  const { client } = useApi();
  return useAction(async (directory: boolean) => {
    const path = await pickPath(directory);
    if (!path) return null;
    return unwrap(await client.POST("/api/roots", { body: { path, watch: true, include_hidden: false } }));
  }, "Added — indexing in the background");
}

function statusLine(s: Source, progress?: { p: number; m: string | null }): string {
  if (s.status === "indexing" && progress) return progress.m ?? `${Math.round(progress.p * 100)}%`;
  if (s.status === "failed") return s.error?.split("\n")[0] ?? "failed";
  if (s.status === "indexed") return `${s.kind} · ${(s.size / 1024 / 1024).toFixed(s.size > 1024 * 1024 ? 1 : 2)} MB`;
  if (s.status === "metadata") return "Metadata only · content format not supported";
  return s.status;
}

export function SourcesPanel() {
  const { client } = useApi();
  const { data: roots } = useRoots();
  const { data: jobs } = useJobs();
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const { data: page, isPending, error, refetch } = useFilePage(filter, offset);
  const sources = page?.sources;
  const active = ui.use((s) => (s.selection.kind === "source" ? s.selection.id : null));
  const addRoot = useAddRoot();
  const removeRoot = useAction(async (id: string) => unwrap(await client.DELETE("/api/roots/{root_id}", { params: { path: { root_id: id } } })), "Folder removed — its knowledge is kept");
  const reindex = useAction(async (id: string) => unwrap(await client.POST("/api/sources/{source_id}/reindex", { params: { path: { source_id: id } } })), "Re-indexing");
  const forget = useAction(async (id: string) => {
    if (!window.confirm("Forget this file? Its passages and unverified facts are removed. Verified facts that relied only on it are flagged for review.")) return null;
    return unwrap(await client.POST("/api/sources/{source_id}/forget", { params: { path: { source_id: id } } }));
  }, "Forgotten");

  const running = new Map((jobs ?? []).filter((j) => j.status === "running" && j.kind === "index_source")
    .map((j) => [String(j.payload.source_id), { p: j.progress, m: j.message }]));
  const shown = sources ?? [];

  return (
    <>
      <div style={{ padding: "10px 12px" }}><button type="button" className="btn primary" style={{ width: "100%" }} onClick={() => ui.set({ modal: "scan" })}><Icon name="search" /> Scan my computer</button></div>
      <div className="sidebar-head">
        <h2>Folders</h2>
        <button type="button" className="btn sm" onClick={() => addRoot.mutate(true)} title="Add a folder"><Icon name="folder" size={13} /> Add</button>
        <button type="button" className="btn sm icon-only" onClick={() => addRoot.mutate(false)} title="Add a single file"><Icon name="plus" size={13} /></button>
      </div>
      {(roots ?? []).map((r) => (
        <div key={r.id} className="list-row" style={{ cursor: "default", minHeight: 30 }}>
          <Icon name={r.kind === "folder" ? "folder" : "file"} size={14} className="muted" />
          <span className="ellipsis grow small" title={r.path}>{basename(r.path)}</span>
          <div className="row-actions" style={{ opacity: 1 }}>
            <button type="button" className="btn ghost sm icon-only" title="Stop tracking (knowledge is kept)" onClick={() => removeRoot.mutate(r.id)}><Icon name="x" size={13} /></button>
          </div>
        </div>
      ))}
      <div className="sidebar-head" style={{ paddingTop: 14 }}>
        <h2>Files</h2>
        <span className="tiny muted">{page?.total ?? 0}</span>
      </div>
      {((page?.total ?? 0) > 6 || !!filter) && (
        <div style={{ padding: "0 12px 8px" }}>
          <input className="input" style={{ width: "100%" }} placeholder="Search all file paths…" value={filter} onChange={(e) => { setFilter(e.target.value); setOffset(0); }} />
        </div>
      )}
      <div className="scroll">
        {isPending && <p role="status" className="empty-inline">Loading files…</p>}
        {error && <div role="alert" className="empty-inline">Could not load files. <button type="button" className="btn sm" onClick={() => void refetch()}>Retry</button></div>}
        {!isPending && !error && !sources?.length && <div className="empty-inline">{filter ? "No files match this search." : "Add a folder or scan your computer to begin."}</div>}
        {shown.map((s) => (
          <div key={s.id} className={`list-row ${active === s.id ? "active" : ""}`} onClick={() => selectSource(s.id)} title={s.error ?? s.path}>
            <div className="file-icon"><Icon name={kindIcon(s.kind)} size={14} /></div>
            <div className="grow">
              <div className="title ellipsis">{basename(s.path)}</div>
              <div className={`meta ellipsis`} style={s.status === "failed" ? { color: "var(--bad)" } : undefined}>{statusLine(s, running.get(s.id))}</div>
              {s.status === "indexing" && running.has(s.id) && (
                <div className="progress" style={{ marginTop: 4 }}><div style={{ width: `${Math.max(3, Math.round((running.get(s.id)?.p ?? 0) * 100))}%` }} /></div>
              )}
            </div>
            {s.status !== "indexed" && s.status !== "indexing" && <span className={`badge ${s.status}`}>{s.status}</span>}
            {s.status === "indexing" && <Icon name="loader" size={14} spin className="muted" />}
            <div className="row-actions">
              {s.kind !== "other" && <button type="button" className="btn ghost sm icon-only" title="Re-index" onClick={(e) => { e.stopPropagation(); reindex.mutate(s.id); }}><Icon name="refresh" size={13} /></button>}
              <button type="button" className="btn ghost sm icon-only danger" title="Forget this file" onClick={(e) => { e.stopPropagation(); forget.mutate(s.id); }}><Icon name="trash" size={13} /></button>
            </div>
          </div>
        ))}
      </div>
      {!!page?.total && <div className="row" style={{ padding: 10 }}>
        <button type="button" className="btn sm" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous</button>
        <span className="small muted">{offset + 1}–{offset + shown.length} / {page.total}</span>
        <button type="button" className="btn sm" disabled={offset + shown.length >= page.total} onClick={() => setOffset(offset + 100)}>Next</button>
      </div>}
    </>
  );
}
