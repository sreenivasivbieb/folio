/**
 * Review queue: conflicts first, then flagged and low-confidence proposals, plus possible
 * duplicates and failed extractions — a few minutes of review covers the riskiest facts.
 * Keyboard: J/K move, V verify, R reject.
 */
import type { Claim } from "@folio/api-client";
import { useEffect, useMemo, useState } from "react";
import { unwrap, useApi } from "@/api/client";
import { useAction, useKnowledgeActions, useReview } from "@/api/queries";
import { EntityName } from "@/components/Badges";
import { Icon } from "@/components/Icon";
import { ClaimRow, type EntityRef } from "@/features/claims/ClaimRow";
import { useSourceNames } from "@/features/sources/useSourceNames";
import { basename, predicateLabel } from "@/lib/format";
import { selectEntity } from "@/state/selection";

export function ReviewPanel() {
  const { client } = useApi();
  const { data } = useReview();
  const sources = useSourceNames();
  const actions = useKnowledgeActions();
  const [cursor, setCursor] = useState(0);
  const dismissSuggestion = useAction(async (id: string) =>
    unwrap(await client.POST("/api/review/suggestions/{suggestion_id}/dismiss", { params: { path: { suggestion_id: id } } })));
  const dismissIssue = useAction(async (id: string) =>
    unwrap(await client.POST("/api/review/issues/{issue_id}/dismiss", { params: { path: { issue_id: id } } })));

  const queue: Claim[] = useMemo(
    () => (data ? [...data.conflicts.flatMap((c) => c.claims.filter((x) => x.status === "proposed")), ...data.flagged, ...data.proposed] : []),
    [data],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select") || e.ctrlKey || e.metaKey) return;
      const c = queue[cursor];
      if (e.key === "j") setCursor((i) => Math.min(i + 1, queue.length - 1));
      else if (e.key === "k") setCursor((i) => Math.max(i - 1, 0));
      else if (c && e.key === "v") actions.setClaimStatus.mutate({ ids: [c.id], status: "verified" });
      else if (c && e.key === "r") actions.setClaimStatus.mutate({ ids: [c.id], status: "rejected" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queue, cursor, actions.setClaimStatus]);

  if (!data) return <div className="empty-inline"><Icon name="loader" spin /></div>;
  const entities = data.entities as Record<string, EntityRef>;
  const total = queue.length + data.merge_suggestions.length + data.extraction_issues.length;

  return (
    <div className="scroll">
      {total === 0 && (
        <div className="empty-inline">
          <Icon name="check" size={20} style={{ margin: "0 auto 8px" }} />
          Nothing to review. New proposals from the AI appear here, riskiest first.
        </div>
      )}
      {data.conflicts.length > 0 && (
        <>
          <div className="sidebar-head"><h2>Conflicts</h2><span className="badge bad">{data.conflicts.length}</span></div>
          {data.conflicts.map((c) => (
            <div key={`${c.subject_id}-${c.predicate}`} style={{ padding: "0 10px 10px" }}>
              <div className="small text-2" style={{ margin: "0 4px 4px" }}>
                <button type="button" className="entity-link" onClick={() => selectEntity(c.subject_id)}>{entities[c.subject_id]?.name}</button>
                {" "}has different <b>{predicateLabel(c.predicate)}</b> values — keep the right one
              </div>
              {c.claims.map((cl) => <ClaimRow key={cl.id} claim={cl} entities={entities} sources={sources} showSubject={false} />)}
            </div>
          ))}
        </>
      )}
      {data.merge_suggestions.length > 0 && (
        <>
          <div className="sidebar-head"><h2>Possible duplicates</h2><span className="tiny muted">{data.merge_suggestions.length}</span></div>
          {data.merge_suggestions.map((s) => {
            const a = entities[s.entity_a];
            const b = entities[s.entity_b];
            if (!a || !b) return null;
            return (
              <div key={s.id} className="list-row" style={{ cursor: "default", flexWrap: "wrap" }}>
                <EntityName name={a.name} type={a.type} onClick={() => selectEntity(a.id)} />
                <Icon name="merge" size={13} className="muted" />
                <EntityName name={b.name} type={b.type} onClick={() => selectEntity(b.id)} />
                <span className="spacer" />
                <button type="button" className="btn sm" onClick={() => actions.merge.mutate({ keep: a.id, merge: b.id })}>Merge</button>
                <button type="button" className="btn sm ghost" onClick={() => dismissSuggestion.mutate(s.id)}>Different</button>
              </div>
            );
          })}
        </>
      )}
      {queue.length > 0 && (
        <>
          <div className="sidebar-head">
            <h2>To review</h2>
            <span className="tiny muted"><span className="kbd">J</span><span className="kbd">K</span> move · <span className="kbd">V</span> verify · <span className="kbd">R</span> reject</span>
          </div>
          <div style={{ padding: "0 8px" }}>
            {queue.map((c, i) => (
              <div key={c.id} style={{ borderRadius: 8, boxShadow: i === cursor ? "0 0 0 2px var(--accent)" : undefined }} onMouseEnter={() => setCursor(i)}>
                <ClaimRow claim={c} entities={entities} sources={sources} />
              </div>
            ))}
          </div>
        </>
      )}
      {data.extraction_issues.length > 0 && (
        <>
          <div className="sidebar-head"><h2>Extraction failed</h2><span className="tiny muted">{data.extraction_issues.length}</span></div>
          {data.extraction_issues.map((i) => (
            <div key={i.id} className="list-row" style={{ cursor: "default", alignItems: "flex-start" }}>
              <Icon name="alert" size={14} style={{ color: "var(--bad)", marginTop: 2 }} />
              <div className="grow small"><b>{i.path ? basename(i.path) : i.source_id}</b><div className="tiny text-2">{i.reason}</div></div>
              <button type="button" className="btn sm ghost" onClick={() => dismissIssue.mutate(i.id)}>Dismiss</button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
