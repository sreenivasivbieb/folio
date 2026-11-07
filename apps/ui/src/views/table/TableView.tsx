/** Table: all claims for an entity or a filter — sortable, inline-editable, bulk verify/reject. */
import type { Claim, EntityNode } from "@folio/api-client";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type RowSelectionState,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { useKnowledgeActions, useTable } from "@/api/queries";
import { Confidence, EntityName, StatusBadge } from "@/components/Badges";
import { useSourceNames } from "@/features/sources/useSourceNames";
import { locatorLabel, predicateLabel, valueText } from "@/lib/format";
import { useSchemaDef } from "@/lib/schema";
import { openEvidence, selectClaims, selectEntity, ui } from "@/state/selection";

function EditableCell({ value, type, onSave }: { value: string; type: "text" | "date"; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  if (!editing) {
    return (
      <span onDoubleClick={() => { setDraft(value); setEditing(true); }} title="Double-click to edit" style={{ cursor: "text" }}>
        {value || <span className="muted">—</span>}
      </span>
    );
  }
  const commit = () => {
    setEditing(false);
    if (draft !== value) onSave(draft);
  };
  return (
    <input
      className="input cell-edit"
      type={type}
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setEditing(false);
      }}
    />
  );
}

export function TableView() {
  const focus = ui.use((s) => s.focusEntity);
  const [scoped, setScoped] = useState(true);
  const [status, setStatus] = useState<string>("");
  const [entityType, setEntityType] = useState<string>("");
  const [predicate, setPredicate] = useState("");
  const { data } = useTable({
    entity_id: scoped && focus ? focus : undefined,
    status: status ? [status] : undefined,
    entity_type: entityType || undefined,
    predicate: predicate || undefined,
  });
  const schema = useSchemaDef();
  const sources = useSourceNames();
  const actions = useKnowledgeActions();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const entities = (data?.entities ?? {}) as Record<string, EntityNode>;

  const columns = useMemo<ColumnDef<Claim>[]>(
    () => [
      {
        id: "select",
        header: ({ table }) => (
          <input type="checkbox" checked={table.getIsAllRowsSelected()} onChange={table.getToggleAllRowsSelectedHandler()} aria-label="Select all" />
        ),
        cell: ({ row }) => <input type="checkbox" checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} aria-label="Select row" />,
        size: 28,
      },
      { id: "status", header: "Status", accessorKey: "status", cell: (c) => <StatusBadge status={c.getValue<string>()} /> },
      {
        id: "subject",
        header: "Subject",
        accessorFn: (c) => entities[c.subject_id]?.name ?? "",
        cell: ({ row }) => {
          const e = entities[row.original.subject_id];
          return e ? <EntityName name={e.name} type={e.type} onClick={() => selectEntity(e.id)} /> : null;
        },
      },
      { id: "predicate", header: "Predicate", accessorKey: "predicate", cell: (c) => predicateLabel(c.getValue<string>()) },
      {
        id: "value",
        header: "Value / object",
        accessorFn: (c) => (c.object_id ? entities[c.object_id]?.name ?? "" : valueText(c)),
        cell: ({ row }) => {
          const c = row.original;
          if (c.object_id) {
            const o = entities[c.object_id];
            return o ? <EntityName name={o.name} type={o.type} onClick={() => selectEntity(o.id)} /> : null;
          }
          if (c.predicate === "represented_by") return sources[String(c.value)] ?? "file";
          return <EditableCell value={valueText(c)} type="text" onSave={(v) => actions.editClaim.mutate({ id: c.id, changes: { value: v } })} />;
        },
      },
      {
        id: "date",
        header: "Date",
        accessorFn: (c) => c.valid_from ?? "",
        cell: ({ row }) => (
          <EditableCell
            value={row.original.valid_from ?? ""}
            type="date"
            onSave={(v) => actions.editClaim.mutate({ id: row.original.id, changes: { valid_from: v || null } })}
          />
        ),
      },
      { id: "confidence", header: "Conf.", accessorKey: "confidence", cell: (c) => <Confidence value={c.getValue<number>()} /> },
      {
        id: "source",
        header: "Source",
        accessorFn: (c) => (c.evidence?.[0]?.source_id ? sources[c.evidence[0].source_id] ?? "" : ""),
        cell: ({ row }) => {
          const ev = row.original.evidence?.[0];
          if (!ev) return <span className="muted">{row.original.extractor.kind}</span>;
          return (
            <button type="button" className="evlink" title={ev.quote} onClick={() => openEvidence(ev)}>
              {ev.source_id ? `${sources[ev.source_id] ?? "source"} ${locatorLabel(ev.locator)}` : locatorLabel(ev.locator)}
            </button>
          );
        },
      },
    ],
    [entities, sources, actions.editClaim],
  );

  const table = useReactTable({
    data: data?.claims ?? [],
    columns,
    state: { sorting, rowSelection },
    getRowId: (c) => c.id,
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const chosen = Object.keys(rowSelection).filter((k) => rowSelection[k]);

  return (
    <div className="view" style={{ display: "flex", flexDirection: "column" }}>
      <div className="toolbar">
        <label className="row small">
          <input type="checkbox" checked={scoped} disabled={!focus} onChange={(e) => setScoped(e.target.checked)} />
          only {focus && entities[focus] ? `“${entities[focus].name}”` : "selected entity"}
        </label>
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status filter">
          <option value="">any status</option>
          <option value="proposed">proposed</option>
          <option value="verified">verified</option>
          <option value="rejected">rejected</option>
        </select>
        <select className="input" value={entityType} onChange={(e) => setEntityType(e.target.value)} aria-label="Type filter">
          <option value="">any type</option>
          {Object.keys(schema?.entity_types ?? {}).map((t) => <option key={t}>{t}</option>)}
        </select>
        <input className="input" placeholder="predicate…" value={predicate} onChange={(e) => setPredicate(e.target.value)} style={{ width: 120 }} />
        <span className="spacer" />
        {chosen.length > 0 && (
          <>
            <span className="small muted">{chosen.length} selected</span>
            <button type="button" className="btn small ok" onClick={() => { actions.setClaimStatus.mutate({ ids: chosen, status: "verified" }); setRowSelection({}); }}>Verify</button>
            <button type="button" className="btn small bad" onClick={() => { actions.setClaimStatus.mutate({ ids: chosen, status: "rejected" }); setRowSelection({}); }}>Reject</button>
          </>
        )}
        <span className="small muted">{data?.claims.length ?? 0} claims</span>
      </div>
      <div className="scroll">
        <table className="grid">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th key={h.id} onClick={h.column.getToggleSortingHandler()}>
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {{ asc: " ▲", desc: " ▼" }[h.column.getIsSorted() as string] ?? ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className={row.original.status} onClick={() => selectClaims([row.original.id])}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} onClick={cell.column.id === "select" ? (e) => e.stopPropagation() : undefined}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {data?.claims.length === 0 && <div className="empty">No claims match.</div>}
      </div>
    </div>
  );
}
