/**
 * One claim, the same everywhere (card, review queue, timeline): what it says, how sure we are,
 * where it comes from (click to open the evidence at the exact page/second), and inline actions.
 */
import type { Claim } from "@folio/api-client";
import { useState } from "react";
import { useKnowledgeActions } from "@/api/queries";
import { Confidence, EntityName, StatusBadge } from "@/components/Badges";
import { locatorLabel, predicateLabel, shortDate, valueText } from "@/lib/format";
import { openEvidence, selectClaims, selectEntity, ui } from "@/state/selection";
import { ClaimHistory } from "./ClaimHistory";

export interface EntityRef {
  id: string;
  name: string;
  type: string;
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

  const save = () => {
    const changes: Record<string, unknown> = {};
    if (claim.kind === "attribute" && draft !== valueText(claim)) changes.value = draft;
    if ((date || null) !== (claim.valid_from ?? null)) changes.valid_from = date || null;
    if (Object.keys(changes).length) actions.editClaim.mutate({ id: claim.id, changes });
    setEditing(false);
  };

  return (
    <div className={`claim ${claim.status} ${selected ? "selected" : ""}`} onClick={() => selectClaims([claim.id])}>
      <div className="body">
        <div className="row" style={{ flexWrap: "wrap" }}>
          {showSubject && subject && subject.id !== selfId && <EntityName name={subject.name} type={subject.type} onClick={() => selectEntity(subject.id)} />}
          <span className="muted">{predicateLabel(claim.predicate)}</span>
          {object && object.id !== selfId && <EntityName name={object.name} type={object.type} onClick={() => selectEntity(object.id)} />}
          {claim.kind === "attribute" && !editing && (
            <span>{claim.predicate === "represented_by" ? sources?.[String(claim.value)] ?? "this file" : valueText(claim)}</span>
          )}
          {claim.valid_from && !editing && <span className="badge">{shortDate(claim.valid_from)}</span>}
        </div>
        {editing && (
          <div className="row" style={{ marginTop: 4 }} onClick={(e) => e.stopPropagation()}>
            {claim.kind === "attribute" && (
              <input className="input" value={draft} autoFocus onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
            )}
            <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            <button type="button" className="btn small primary" onClick={save}>Save</button>
            <button type="button" className="btn small" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        )}
        <div className="row small" style={{ marginTop: 2, flexWrap: "wrap" }}>
          <StatusBadge status={claim.status} />
          <Confidence value={claim.confidence} />
          <span className="muted">{claim.extractor.kind === "model" ? claim.extractor.model : claim.extractor.kind}</span>
          {claim.needs_review && <span className="badge proposed">needs review</span>}
          {(claim.evidence ?? []).slice(0, 4).map((ev) => (
            <button
              type="button"
              key={ev.id}
              className="evlink"
              title={ev.quote}
              onClick={(e) => {
                e.stopPropagation();
                openEvidence(ev);
              }}
            >
              {ev.source_id ? `${sources?.[ev.source_id] ?? "source"} ${locatorLabel(ev.locator)}` : locatorLabel(ev.locator)}
            </button>
          ))}
          {(claim.evidence?.length ?? 0) > 4 && <span className="muted">+{(claim.evidence?.length ?? 0) - 4}</span>}
        </div>
        {history && <ClaimHistory claimId={claim.id} />}
      </div>
      <div className="actions" onClick={(e) => e.stopPropagation()}>
        {claim.status !== "verified" && (
          <button type="button" className="btn small icon ok" title="Verify (V)" onClick={() => actions.setClaimStatus.mutate({ ids: [claim.id], status: "verified" })}>✓</button>
        )}
        {claim.status !== "rejected" && (
          <button type="button" className="btn small icon bad" title="Reject (R)" onClick={() => actions.setClaimStatus.mutate({ ids: [claim.id], status: "rejected" })}>✕</button>
        )}
        <button type="button" className="btn small icon" title="Edit" onClick={() => setEditing((v) => !v)}>✎</button>
        <button type="button" className="btn small icon" title="History (who/what/when)" onClick={() => setHistory((v) => !v)}>⏱</button>
      </div>
    </div>
  );
}
