/**
 * One claim, the same everywhere (card, review queue, timeline): what it says, how sure we are,
 * where it comes from (click to open the evidence at the exact page/second), and inline actions.
 * The left stripe shows status: solid green = verified, dashed amber = proposed.
 */
import type { Claim } from "@folio/api-client";
import { useState } from "react";
import { useKnowledgeActions } from "@/api/queries";
import { Confidence, EntityName } from "@/components/Badges";
import { Icon } from "@/components/Icon";
import { basename, locatorLabel, predicateLabel, shortDate, valueText } from "@/lib/format";
import { openEvidence, selectClaims, selectEntity, ui } from "@/state/selection";
import { ClaimHistory } from "./ClaimHistory";

export interface EntityRef {
  id: string;
  name: string;
  type: string;
}

function who(c: Claim): string {
  if (c.extractor.kind === "model") return c.extractor.model === "rules-v1" ? "pattern" : "AI";
  return c.extractor.kind;
}

export function ClaimRow({ claim, entities, showSubject = true, sources, selfId }: {
  claim: Claim;
  entities: Record<string, EntityRef | undefined>;
  showSubject?: boolean;
  sources?: Record<string, string>;
  /** The entity whose card/timeline this row is shown in: not repeated in the row. */
  selfId?: string;
}) {
  const actions = useKnowledgeActions();
  const selected = ui.use((s) => s.selection.kind === "claim" && s.selection.ids.includes(claim.id));
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(valueText(claim));
  const [date, setDate] = useState(claim.valid_from ?? "");
  const [history, setHistory] = useState(false);
  const subject = entities[claim.subject_id];
  const object = claim.object_id ? entities[claim.object_id] : undefined;
  const evidence = claim.evidence ?? [];

  const save = () => {
    const changes: Record<string, unknown> = {};
    if (claim.kind === "attribute" && draft !== valueText(claim)) changes.value = draft;
    if ((date || null) !== (claim.valid_from ?? null)) changes.valid_from = date || null;
    if (Object.keys(changes).length) actions.editClaim.mutate({ id: claim.id, changes });
    setEditing(false);
  };

  return (
    <div className={`claim ${claim.status} ${selected ? "selected" : ""}`} onClick={() => selectClaims([claim.id])}>
      <div className="claim-text">
        {showSubject && subject && subject.id !== selfId && <EntityName name={subject.name} type={subject.type} onClick={() => selectEntity(subject.id)} />}
        <span className="pred">{predicateLabel(claim.predicate)}</span>
        {object && object.id !== selfId && <EntityName name={object.name} type={object.type} onClick={() => selectEntity(object.id)} />}
        {claim.kind === "attribute" && !editing && (
          <span style={{ fontWeight: 500 }}>
            {claim.predicate === "represented_by" ? sources?.[String(claim.value)] ?? "this file" : valueText(claim)}
          </span>
        )}
        {claim.valid_from && !editing && claim.predicate !== "mentioned" && <span className="badge">{shortDate(claim.valid_from)}</span>}
      </div>
      {editing && (
        <div className="row" style={{ marginTop: 6 }} onClick={(e) => e.stopPropagation()}>
          {claim.kind === "attribute" && (
            <input className="input grow" value={draft} autoFocus onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
          )}
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <button type="button" className="btn sm primary" onClick={save}>Save</button>
          <button type="button" className="btn sm ghost" onClick={() => setEditing(false)}>Cancel</button>
        </div>
      )}
      <div className="claim-meta">
        {claim.status === "proposed" && <span className="badge proposed">proposed</span>}
        {claim.status === "rejected" && <span className="badge rejected">rejected</span>}
        {claim.needs_review && <span className="badge warn">needs review</span>}
        <Confidence value={claim.confidence} />
        <span>· {who(claim)}</span>
        {evidence.slice(0, 3).map((ev) => (
          <button type="button" key={ev.id} className="evlink" title={ev.quote}
            onClick={(e) => { e.stopPropagation(); openEvidence(ev); }}>
            <Icon name={ev.locator.kind === "label" ? "mic" : "quote"} size={10} />
            {ev.source_id ? `${basename(sources?.[ev.source_id] ?? "file")} ${locatorLabel(ev.locator)}` : locatorLabel(ev.locator)}
          </button>
        ))}
        {evidence.length > 3 && <span>+{evidence.length - 3} more</span>}
      </div>
      {history && <ClaimHistory claimId={claim.id} />}
      <div className="actions" onClick={(e) => e.stopPropagation()}>
        {claim.status !== "verified" && (
          <button type="button" className="btn ghost sm icon-only success" title="Verify (V)" onClick={() => actions.setClaimStatus.mutate({ ids: [claim.id], status: "verified" })}><Icon name="check" size={14} /></button>
        )}
        {claim.status !== "rejected" && (
          <button type="button" className="btn ghost sm icon-only danger" title="Reject (R)" onClick={() => actions.setClaimStatus.mutate({ ids: [claim.id], status: "rejected" })}><Icon name="x" size={14} /></button>
        )}
        <button type="button" className="btn ghost sm icon-only" title="Edit" onClick={() => setEditing((v) => !v)}><Icon name="pencil" size={13} /></button>
        <button type="button" className="btn ghost sm icon-only" title="History: who, what, when" onClick={() => setHistory((v) => !v)}><Icon name="history" size={13} /></button>
      </div>
    </div>
  );
}
