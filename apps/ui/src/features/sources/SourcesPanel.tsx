/** Library: the files dumped into Folio's own storage, with their index status. */
import type { Source } from "@folio/api-client";
import { useState } from "react";
import { unwrap, useApi } from "@/api/client";
import { useAction, useFilePage, useFileTags, useJobs, useVault, useVaultActions } from "@/api/queries";
import { Icon, kindIcon } from "@/components/Icon";
import { basename, fileSize } from "@/lib/format";
import { openAdd, selectSource, ui } from "@/state/selection";

function statusLine(s: Source, progress?: { p: number; m: string | null }): string {
  if (s.status === "indexing" && progress) return progress.m ?? `${Math.round(progress.p * 100)}%`;
  if (s.status === "failed") return s.error?.split("\n")[0] ?? "failed";
  if (s.status === "indexed") return `${s.kind} · ${fileSize(s.size)}`;
  if (s.status === "metadata") return "Metadata only · content format not supported";
  return s.status;
}

export function SourcesPanel() {
  const { client } = useApi();
  const { data: vault } = useVault();
  const vaultActions = useVaultActions();
  const { data: jobs } = useJobs();
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [tag, setTag] = useState<{ id: string; name: string } | null>(null);
  const [showAllTags, setShowAllTags] = useState(false);
  const { data: page, isPending, error, refetch } = useFilePage(filter, offset, tag?.id ?? null);
  const { data: tags } = useFileTags();
  const pickTag = (t: { id: string; name: string } | null) => { setTag(t && tag?.id === t.id ? null : t); setOffset(0); };
  const sources = page?.sources;
  const active = ui.use((s) => (s.selection.kind === "source" ? s.selection.id : null));
  const reindex = useAction(async (id: string) => unwrap(await client.POST("/api/sources/{source_id}/reindex", { params: { path: { source_id: id } } })), "Re-indexing");

  const running = new Map((jobs ?? []).filter((j) => j.status === "running" && j.kind === "index_source")
    .map((j) => [String(j.payload.source_id), { p: j.progress, m: j.message }]));
  const shown = sources ?? [];

  return (
    <>
      <div style={{ padding: "12px 12px 4px" }}>
        <button type="button" className="btn primary" style={{ width: "100%" }} onClick={() => openAdd()}><Icon name="plus" /> Add to Folio</button>
        {vault && (
          <div className="vault-meta" title={vault.path}>
            <Icon name="database" size={12} /> {vault.files} file{vault.files === 1 ? "" : "s"} · {fileSize(vault.bytes)} stored in Folio
          </div>
        )}
      </div>
      {!!tags?.length && (
        <div className="tag-row" role="toolbar" aria-label="Filter by topic">
          {(showAllTags ? tags : tags.slice(0, 8)).map((t) => (
            <button type="button" key={t.id} className="tag-chip" aria-pressed={tag?.id === t.id} onClick={() => pickTag(t)} title={`${t.type} · ${t.count} file(s)`}>
              {t.name}<span>{t.count}</span>
            </button>
          ))}
        {tags.length > 8 && (
            <button type="button" className="tag-chip more" onClick={() => setShowAllTags((v) => !v)}>
              {showAllTags ? "less" : `+${tags.length - 8} more`}
            </button>
          )}
        </div>
      )}
      <div className="sidebar-head" style={{ paddingTop: 14 }}>
        <h2>{tag ? <>Files · <span className="tag-active">{tag.name}<button type="button" aria-label="Clear topic filter" onClick={() => pickTag(null)}>×</button></span></> : "Files"}</h2>
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
        {!isPending && !error && !sources?.length && <div className="empty-inline">{filter ? "No files match this search." : tag ? "No files under this topic." : "Nothing here yet. Add files, or drop them onto the window."}</div>}
        {shown.map((s) => (
          <div key={s.id} className={`list-row ${active === s.id ? "active" : ""}`} onClick={() => selectSource(s.id)} title={s.error ?? s.path}>
            <div className="file-icon"><Icon name={kindIcon(s.kind)} size={14} /></div>
            <div className="grow">
              <div className="title ellipsis">{s.title ?? basename(s.path)}</div>
              {s.title && <div className="meta ellipsis file-name">{basename(s.path)}</div>}
              {s.description
                ? <div className="meta ellipsis file-desc" title={s.description}>{s.description}</div>
                : <div className={`meta ellipsis`} style={s.status === "failed" ? { color: "var(--bad)" } : undefined}>{statusLine(s, running.get(s.id))}</div>}
              {!!s.tags?.length && (
                <div className="file-tags">
                  {s.tags.slice(0, 4).map((t) => (
                    <button type="button" key={t.id} className="tag-chip sm" onClick={(e) => { e.stopPropagation(); pickTag(t); }}>{t.name}</button>
                  ))}
                  {s.tags.length > 4 && <span className="tiny muted">+{s.tags.length - 4}</span>}
                </div>
              )}
              {s.status === "indexing" && running.has(s.id) && (
                <div className="progress" style={{ marginTop: 4 }}><div style={{ width: `${Math.max(3, Math.round((running.get(s.id)?.p ?? 0) * 100))}%` }} /></div>
              )}
            </div>
            {s.status !== "indexed" && s.status !== "indexing" && <span className={`badge ${s.status}`}>{s.status}</span>}
            {s.status === "indexing" && <Icon name="loader" size={14} spin className="muted" />}
            <div className="row-actions">
              {s.kind !== "other" && <button type="button" className="btn ghost sm icon-only" title="Re-index" onClick={(e) => { e.stopPropagation(); reindex.mutate(s.id); }}><Icon name="refresh" size={13} /></button>}
              <button type="button" className="btn ghost sm icon-only" title="Label this file (type or speak)"
                onClick={(e) => { e.stopPropagation(); selectSource(s.id); setTimeout(() => document.getElementById("label-input")?.focus(), 50); }}><Icon name="tag" size={13} /></button>
              <button type="button" className="btn ghost sm icon-only" title="Export to a folder" onClick={(e) => { e.stopPropagation(); ui.set({ modal: "export", exportId: s.id }); }}><Icon name="external" size={13} /></button>
              <button type="button" className="btn ghost sm icon-only danger" title="Move to trash" onClick={(e) => { e.stopPropagation(); vaultActions.trash.mutate(s.id); }}><Icon name="trash" size={13} /></button>
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
