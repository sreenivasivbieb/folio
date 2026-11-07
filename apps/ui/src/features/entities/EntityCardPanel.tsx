/** The entity card (FR-5): every data point about an entity, grouped, each opening its source. */
import { useEffect, useState } from "react";
import { useEntityCard, useKnowledgeActions } from "@/api/queries";
import { StatusBadge, TypeDot } from "@/components/Badges";
import { ClaimRow, type EntityRef } from "@/features/claims/ClaimRow";
import { useSourceNames } from "@/features/sources/useSourceNames";
import { basename, locatorLabel, predicateLabel } from "@/lib/format";
import { useSchemaDef } from "@/lib/schema";
import { openEvidence, selectSource, ui } from "@/state/selection";
import { AddFact } from "./AddFact";

export function EntityCardPanel({ entityId }: { entityId: string }) {
  const { data: card, isLoading, error } = useEntityCard(entityId);
  const schema = useSchemaDef();
  const actions = useKnowledgeActions();
  const sources = useSourceNames();
  const [name, setName] = useState("");
  const [alias, setAlias] = useState("");
  useEffect(() => setName(card?.entity.name ?? ""), [card?.entity.name]);

  if (isLoading) return <div className="empty">Loading…</div>;
  if (error || !card) return <div className="empty">{error?.message ?? "Not found"}</div>;
  const e = card.entity;
  const entities: Record<string, EntityRef> = { ...card.related, [e.id]: e };
  const groups = Object.entries(card.groups).sort(([a], [b]) => (a === "file" ? -1 : b === "file" ? 1 : a.localeCompare(b)));

  return (
    <div>
      <div className="section">
        <div className="row">
          <TypeDot type={e.type} />
          <input
            className="entity-title"
            value={name}
            onChange={(ev) => setName(ev.target.value)}
            onBlur={() => name.trim() && name !== e.name && actions.updateEntity.mutate({ id: e.id, changes: { name } })}
            onKeyDown={(ev) => ev.key === "Enter" && (ev.target as HTMLInputElement).blur()}
            aria-label="Entity name"
          />
        </div>
        <div className="row" style={{ marginTop: 6, flexWrap: "wrap" }}>
          <select
            className="input"
            value={e.type}
            onChange={(ev) => actions.updateEntity.mutate({ id: e.id, changes: { type: ev.target.value } })}
            aria-label="Entity type"
          >
            {Object.keys(schema?.entity_types ?? { [e.type]: 1 }).map((t) => <option key={t}>{t}</option>)}
          </select>
          <StatusBadge status={e.status} />
          <span className="muted small">by {e.created_by}</span>
          <span className="spacer" />
          {e.status !== "verified" && (
            <button type="button" className="btn small ok" onClick={() => actions.updateEntity.mutate({ id: e.id, changes: { status: "verified" } })}>Verify</button>
          )}
          {e.status !== "rejected" && (
            <button type="button" className="btn small bad" onClick={() => actions.updateEntity.mutate({ id: e.id, changes: { status: "rejected" } })}>Reject</button>
          )}
          <button type="button" className="btn small" onClick={() => ui.set({ focusEntity: e.id, view: "timeline" })}>Timeline</button>
        </div>
        <div style={{ marginTop: 8 }}>
          {(e.aliases ?? []).filter((a) => a !== e.name).map((a) => (
            <span key={a} className="alias">
              {a}
              <button type="button" title="Remove alias" onClick={() => actions.removeAlias.mutate({ id: e.id, alias: a })}>×</button>
            </span>
          ))}
          <input
            className="input small"
            style={{ width: 130 }}
            placeholder="+ alias"
            value={alias}
            onChange={(ev) => setAlias(ev.target.value)}
            onKeyDown={(ev) => {
              if (ev.key === "Enter" && alias.trim()) {
                actions.addAlias.mutate({ id: e.id, alias: alias.trim() });
                setAlias("");
              }
            }}
          />
        </div>
        <div className="row small muted" style={{ marginTop: 6 }}>
          {card.counts.verified ?? 0} verified · {card.counts.proposed ?? 0} proposed · {card.counts.rejected ?? 0} rejected
        </div>
      </div>

      {card.files.length > 0 && (
        <div className="section">
          <h3>Files</h3>
          {card.files.map((f) => (
            <div key={f.id} className="list-item" style={{ padding: "4px 0", border: 0 }} onClick={() => selectSource(f.id)}>
              <span className="badge">{f.kind}</span>
              <span className="ellipsis" title={f.path}>{basename(f.path)}</span>
            </div>
          ))}
        </div>
      )}

      <div className="section">
        <h3>Facts</h3>
        {groups.length === 0 && <div className="muted">No facts yet. Add one below, or label a file by voice.</div>}
        {groups.map(([pred, claims]) => (
          <div key={pred} className="pred-group">
            <div className="label">{predicateLabel(pred)}</div>
            {claims.map((c) => (
              <ClaimRow key={c.id} claim={c} entities={entities} sources={sources} selfId={e.id} />
            ))}
          </div>
        ))}
        <AddFact entity={e} />
      </div>

      {card.passages.length > 0 && (
        <div className="section">
          <h3>Possibly related passages</h3>
          {card.passages.map((p) => (
            <div
              key={p.chunk_id}
              className="list-item"
              style={{ alignItems: "flex-start", flexDirection: "column", gap: 2 }}
              onClick={() =>
                openEvidence({
                  id: p.chunk_id,
                  claim_id: "",
                  source_id: p.source_id,
                  chunk_id: p.chunk_id,
                  locator: p.locator as never,
                  quote: p.text.slice(0, 200),
                })
              }
            >
              <span className="small muted">{basename(p.path)} · {locatorLabel(p.locator as never)}</span>
              <span className="small">{p.text.slice(0, 220)}{p.text.length > 220 ? "…" : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
