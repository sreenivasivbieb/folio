/** Folio's trash: restore, delete forever, or empty it. */
import { useTrash, useVaultActions } from "@/api/queries";
import { Icon, kindIcon } from "@/components/Icon";
import { fileSize, shortDate } from "@/lib/format";

export function TrashPanel() {
  const { data: items, isPending } = useTrash();
  const a = useVaultActions();
  return (
    <>
      <div className="sidebar-head">
        <h2>Trash</h2>
        {!!items?.length && (
          <button type="button" className="btn sm danger"
            onClick={() => window.confirm(`Delete ${items.length} file(s) permanently? This cannot be undone.`) && a.empty.mutate(undefined)}>
            Empty
          </button>
        )}
      </div>
      <div className="scroll">
        {isPending && <p className="empty-inline">Loading…</p>}
        {!isPending && !items?.length && <div className="empty-inline">Trash is empty. Files you delete from Folio wait here until you empty it.</div>}
        {(items ?? []).map((t) => (
          <div key={t.id} className="list-row" style={{ cursor: "default" }} title={t.origin_path ?? t.name}>
            <div className="file-icon"><Icon name={kindIcon(t.kind ?? "other")} size={14} /></div>
            <div className="grow">
              <div className="title ellipsis">{t.name}</div>
              <div className="meta ellipsis">{fileSize(t.size)} · deleted {shortDate(t.trashed_at)}</div>
            </div>
            <div className="row-actions" style={{ opacity: 1 }}>
              <button type="button" className="btn ghost sm icon-only" title="Restore" onClick={() => a.restore.mutate(t.id)}><Icon name="undo" size={13} /></button>
              <button type="button" className="btn ghost sm icon-only danger" title="Delete permanently"
                onClick={() => window.confirm(`Delete “${t.name}” permanently?`) && a.remove.mutate(t.id)}><Icon name="x" size={13} /></button>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
