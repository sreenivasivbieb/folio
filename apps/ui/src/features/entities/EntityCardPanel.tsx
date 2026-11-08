/** The entity card (FR-5): every data point about an entity, grouped, each opening its source. */
import { useEffect, useState } from "react";
import { useEntityCard, useKnowledgeActions, useStatus } from "@/api/queries";
import { TypeDot } from "@/components/Badges";
import { Icon, kindIcon } from "@/components/Icon";
import { ClaimRow, type EntityRef } from "@/features/claims/ClaimRow";
import { useSourceNames } from "@/features/sources/useSourceNames";
import { basename, locatorLabel, predicateLabel } from "@/lib/format";
import { openEvidence, selectSource, ui } from "@/state/selection";
import { AddFact } from "./AddFact";

const GROUP_ORDER = ["file", "mentioned in"];

export function EntityCardPanel({ entityId }: { entityId: string }) {
  const { data: card, isLoading, error } = useEntityCard(entityId);
  const { data: status } = useStatus();
  const actions = useKnowledgeActions();
  const sources = useSourceNames();
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [alias, setAlias] = useState("");
  useEffect(() => setName(card?.entity.name ?? ""), [card?.entity.name]);
  useEffect(() => setType(card?.entity.type ?? ""), [card?.entity.type]);

  if (isLoading) return <div className="empty-inline"><Icon name="loader" spin /></div>;
  if (error || !card) return <div className="empty-inline">{error?.message ?? "Not found"}</div>;
  const e = card.entity;
  const entities: Record<string, EntityRef> = { ...card.related, [e.id]: e };
  const groups = Object.entries(card.groups).sort(([a], [b]) => {
    const ia = GROUP_ORDER.indexOf(a);
    const ib = GROUP_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  const facts = groups.filter(([k]) => k !== "file" && k !== "mentioned in");
  const mentions = card.groups["mentioned in"] ?? [];

  return (
    <div>
      <div className="insp-head">
        <div className="row" style={{ marginBottom: 6 }}>
          <TypeDot type={e.type} size={10} />
          <input className="input" list="entity-types" value={type} onChange={(ev) => setType(ev.target.value)} style={{ height: 24, width: 150, fontSize: 12 }}
            onBlur={() => type.trim() && type !== e.type && actions.updateEntity.mutate({ id: e.id, changes: { type } })}
            onKeyDown={(ev) => ev.key === "Enter" && (ev.target as HTMLInputElement).blur()} aria-label="Entity type" title="Type (any name — no fixed categories)" />
          <datalist id="entity-types">{(status?.types ?? []).map((t) => <option key={t} value={t} />)}</datalist>
          <span className={`badge ${e.status}`}>{e.status === "auto" ? "unconfirmed" : e.status}</span>
          <span className="spacer" />
          {e.status !== "verified" && (
            <button type="button" className="btn sm success" onClick={() => actions.updateEntity.mutate({ id: e.id, changes: { status: "verified" } })} title="Confirm this entity is real"><Icon name="check" size={13} /> Confirm</button>
          )}
          {e.status !== "rejected" && (
            <button type="button" className="btn sm ghost icon-only danger" onClick={() => actions.updateEntity.mutate({ id: e.id, changes: { status: "rejected" } })} title="Not a real entity"><Icon name="trash" size={13} /></button>
          )}
        </div>
        <input className="entity-title" value={name} onChange={(ev) => setName(ev.target.value)}
          onBlur={() => name.trim() && name !== e.name && actions.updateEntity.mutate({ id: e.id, changes: { name } })}
          onKeyDown={(ev) => ev.key === "Enter" && (ev.target as HTMLInputElement).blur()} aria-label="Entity name" />
        <div style={{ marginTop: 8 }}>
          {(e.aliases ?? []).filter((a) => a !== e.name).map((a) => (
            <span key={a} className="alias">{a}<button type="button" title="Remove alias" onClick={() => actions.removeAlias.mutate({ id: e.id, alias: a })}><Icon name="x" size={11} /></button></span>
          ))}
          <input className="input" style={{ width: 120, height: 22, fontSize: 12, borderRadius: 11 }} placeholder="+ also known as" value={alias}
            onChange={(ev) => setAlias(ev.target.value)}
            onKeyDown={(ev) => { if (ev.key === "Enter" && alias.trim()) { actions.addAlias.mutate({ id: e.id, alias: alias.trim() }); setAlias(""); } }} />
        </div>
        <div className="stat-row" style={{ marginTop: 12 }}>
          <div className="stat"><b>{card.counts.verified ?? 0}</b><span>verified</span></div>
          <div className="stat"><b style={{ color: card.counts.proposed ? "var(--warn)" : undefined }}>{card.counts.proposed ?? 0}</b><span>to review</span></div>
          <div className="stat"><b>{card.files.length}</b><span>files</span></div>
          <button type="button" className="stat btn ghost" style={{ height: "auto", flexDirection: "column", alignItems: "flex-start" }} onClick={() => ui.set({ focusEntity: e.id, view: "timeline" })}>
            <Icon name="clock" /><span>timeline</span>
          </button>
        </div>
      </div>

      {card.files.length > 0 && (
        <div className="insp-section">
          <h3><Icon name="file" size={12} /> Files</h3>
          {card.files.map((f) => (
            <div key={f.id} className="file-chip" onClick={() => selectSource(f.id)}>
              <Icon name={kindIcon(f.kind)} size={14} className="muted" />
              <span className="ellipsis grow" title={f.path}>{basename(f.path)}</span>
              <Icon name="chevronRight" size={13} className="muted" />
            </div>
          ))}
        </div>
      )}

      <div className="insp-section">
        <h3><Icon name="layers" size={12} /> Facts</h3>
        {facts.length === 0 && <div className="small muted" style={{ marginBottom: 8 }}>No facts yet. Add one, or say something about it in the composer below.</div>}
        {facts.map(([pred, claims]) => (
          <div key={pred} className="pred-group">
            <div className="label">{predicateLabel(pred)}</div>
            {claims.map((c) => <ClaimRow key={c.id} claim={c} entities={entities} sources={sources} selfId={e.id} />)}
          </div>
        ))}
        <AddFact entity={e} />
      </div>

      {mentions.length > 0 && (
        <div className="insp-section">
          <h3><Icon name="quote" size={12} /> Mentioned in</h3>
          {mentions.map((c) => <ClaimRow key={c.id} claim={c} entities={entities} sources={sources} selfId={e.id} />)}
        </div>
      )}

      {card.passages.length > 0 && (
        <div className="insp-section">
          <h3><Icon name="search" size={12} /> Related passages</h3>
          {card.passages.map((p) => (
            <div key={p.chunk_id} className="passage"
              onClick={() => openEvidence({ id: p.chunk_id, claim_id: "", source_id: p.source_id, chunk_id: p.chunk_id, locator: p.locator as never, quote: p.text.slice(0, 200) })}>
              <div className="tiny muted" style={{ marginBottom: 3 }}>{basename(p.path)} · {locatorLabel(p.locator as never)}</div>
              <div className="small">{p.text.slice(0, 220)}{p.text.length > 220 ? "…" : ""}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
