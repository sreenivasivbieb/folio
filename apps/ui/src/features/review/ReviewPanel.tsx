/**
 * Review queue: conflicts first, then flagged and low-confidence proposals, plus merge
 * suggestions and failed extractions — a few minutes of review covers the riskiest facts.
 * Keyboard: J/K move, V verify, R reject.
 */
import type { Claim } from "@folio/api-client";
import { useEffect, useMemo, useState } from "react";
import { unwrap, useApi } from "@/api/client";
import { useAction, useKnowledgeActions, useReview } from "@/api/queries";
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
    unwrap(await client.POST("/api/review/suggestions/{suggestion_id}/dismiss", { params: { path: { suggestion_id: id } } })),
  );
  const dismissIssue = useAction(async (id: string) =>
    unwrap(await client.POST("/api/review/issues/{issue_id}/dismiss", { params: { path: { issue_id: id } } })),
  );

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

  if (!data) return <div className="empty">Loading…</div>;
  const entities = data.entities as Record<string, EntityRef>;
  const total = queue.length + data.merge_suggestions.length + data.extraction_issues.length;

  return (
    <div className="scroll">
      {total === 0 && <div className="empty">Nothing to review. 🎉</div>}
      {data.conflicts.length > 0 && (
        <div className="section">
          <h3>Conflicts ({data.conflicts.length})</h3>
          {data.conflicts.map((c) => (
            <div key={`${c.subject_id}-${c.predicate}`} className="small" style={{ marginBottom: 6 }}>
              <button type="button" className="evlink" onClick={() => selectEntity(c.subject_id)}>{entities[c.subject_id]?.name}</button>{" "}
              has different <b>{predicateLabel(c.predicate)}</b> values — keep the right one:
              {c.claims.map((cl) => <ClaimRow key={cl.id} claim={cl} entities={entities} sources={sources} showSubject={false} />)}
            </div>
          ))}
        </div>
      )}
      {data.merge_suggestions.length > 0 && (
        <div className="section">
          <h3>Possible duplicates ({data.merge_suggestions.length})</h3>
          {data.merge_suggestions.map((s) => {
            const a = entities[s.entity_a];
            const b = entities[s.entity_b];
            if (!a || !b) return null;
            return (
              <div key={s.id} className="row small" style={{ marginBottom: 6, flexWrap: "wrap" }}>
                <button type="button" className="evlink" onClick={() => selectEntity(a.id)}>{a.name}</button>
                <span className="muted">≈</span>
                <button type="button" className="evlink" onClick={() => selectEntity(b.id)}>{b.name}</button>
                <span className="muted">{Math.round(s.score * 100)}%</span>
                <span className="spacer" />
                <button type="button" className="btn small" onClick={() => actions.merge.mutate({ keep: a.id, merge: b.id })}>Merge</button>
                <button type="button" className="btn small" onClick={() => dismissSuggestion.mutate(s.id)}>Not same</button>
              </div>
            );
          })}
        </div>
      )}
      {queue.length > 0 && (
        <div className="section">
          <h3>Proposed facts ({data.total_proposed}) · <span className="kbd">J</span>/<span className="kbd">K</span> <span className="kbd">V</span> verify <span className="kbd">R</span> reject</h3>
          {queue.map((c, i) => (
            <div key={c.id} style={{ outline: i === cursor ? "2px solid var(--accent)" : undefined, borderRadius: 6 }} onMouseEnter={() => setCursor(i)}>
              <ClaimRow claim={c} entities={entities} sources={sources} />
            </div>
          ))}
        </div>
      )}
      {data.extraction_issues.length > 0 && (
        <div className="section">
          <h3>Extraction failures ({data.extraction_issues.length})</h3>
          {data.extraction_issues.map((i) => (
            <div key={i.id} className="small" style={{ marginBottom: 6 }}>
              <b>{i.path ? basename(i.path) : i.source_id}</b>: {i.reason}{" "}
              <button type="button" className="btn small" onClick={() => dismissIssue.mutate(i.id)}>Dismiss</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
