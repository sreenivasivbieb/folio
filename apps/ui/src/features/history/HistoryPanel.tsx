/** Audit trail: every action as one ledger group; any one can be undone (if nothing later depends on it). */
import { useHistory, useKnowledgeActions } from "@/api/queries";

export function HistoryPanel() {
  const { data } = useHistory();
  const { undo } = useKnowledgeActions();
  if (!data?.length) return <div className="empty">No history yet.</div>;
  return (
    <div className="scroll">
      {data.map((g) => (
        <div key={g.id} className="list-item" style={{ cursor: "default", opacity: g.undone ? 0.5 : 1 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="row small">
              <span className="badge">{g.actor}</span>
              <b>{g.action}</b>
              <span className="muted">{g.n_events} change{g.n_events === 1 ? "" : "s"}</span>
            </div>
            <div className="small muted ellipsis" title={g.summary}>{g.summary}</div>
            <div className="small muted">{new Date(g.ts).toLocaleString()}{g.undone ? " · undone" : ""}</div>
          </div>
          {!g.undone && g.action !== "undo" && g.actor !== "system" && (
            <button type="button" className="btn small" onClick={() => undo.mutate(g.id)}>Undo</button>
          )}
        </div>
      ))}
    </div>
  );
}
