/** Activity: background jobs (with live progress and failure causes) and the undoable history. */
import { useState } from "react";
import { unwrap, useApi } from "@/api/client";
import { useAction, useHistory, useJobs, useKnowledgeActions } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { useSourceNames } from "@/features/sources/useSourceNames";

const KIND_LABEL: Record<string, string> = {
  index_source: "Index",
  extract_source: "Extract",
  download_speech_model: "Download speech model",
};

function ago(ts: string): string {
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(ts).toLocaleDateString();
}

function Jobs() {
  const { client } = useApi();
  const { data: jobs } = useJobs();
  const names = useSourceNames();
  const [open, setOpen] = useState<string | null>(null);
  const retry = useAction(async (id: string) => unwrap(await client.POST("/api/jobs/{job_id}/retry", { params: { path: { job_id: id } } })), "Retrying");
  if (!jobs?.length) return <div className="empty-inline">No background work yet.</div>;
  return (
    <>
      {jobs.map((j) => (
        <div key={j.id} className="list-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 5 }} onClick={() => setOpen(open === j.id ? null : j.id)}>
          <div className="row">
            <span className={`badge ${j.status}`}>{j.status === "running" ? <Icon name="loader" size={11} spin /> : null}{j.status}</span>
            <span className="small" style={{ fontWeight: 550 }}>{KIND_LABEL[j.kind] ?? j.kind}</span>
            <span className="ellipsis small muted grow">{names[String(j.payload.source_id)] ?? ""}</span>
            {j.status === "failed" && (
              <button type="button" className="btn sm" onClick={(e) => { e.stopPropagation(); retry.mutate(j.id); }}><Icon name="refresh" size={12} /> Retry</button>
            )}
          </div>
          {j.status === "running" && <div className="progress"><div style={{ width: `${Math.max(3, Math.round(j.progress * 100))}%` }} /></div>}
          {j.message && <div className="tiny muted ellipsis">{j.message}</div>}
          {j.error && (open === j.id
            ? <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: 0, color: "var(--bad)" }}>{j.error}</pre>
            : <div className="tiny ellipsis" style={{ color: "var(--bad)" }}>{j.error.split("\n")[0]}</div>)}
        </div>
      ))}
    </>
  );
}

function History() {
  const { data } = useHistory();
  const { undo } = useKnowledgeActions();
  if (!data?.length) return <div className="empty-inline">Nothing has happened yet.</div>;
  return (
    <>
      {data.map((g) => (
        <div key={g.id} className="list-row" style={{ cursor: "default", opacity: g.undone ? 0.45 : 1, alignItems: "flex-start" }}>
          <div className="grow">
            <div className="row small">
              <span className="badge">{g.actor.startsWith("model:") ? "AI" : g.actor}</span>
              <b style={{ fontWeight: 550 }}>{g.action.replace(".", " ")}</b>
            </div>
            {g.summary && <div className="tiny text-2 ellipsis" title={g.summary} style={{ marginTop: 2 }}>{g.summary}</div>}
            <div className="tiny muted">{ago(g.ts)} · {g.n_events} change{g.n_events === 1 ? "" : "s"}{g.undone ? " · undone" : ""}</div>
          </div>
          {!g.undone && !["undo", "redo"].includes(g.action) && g.actor !== "system" && (
            <button type="button" className="btn sm ghost" onClick={() => undo.mutate(g.id)} title="Undo this action"><Icon name="undo" size={13} /></button>
          )}
        </div>
      ))}
    </>
  );
}

export function ActivityPanel() {
  const [tab, setTab] = useState<"jobs" | "history">("jobs");
  return (
    <>
      <div className="sidebar-head">
        <div className="seg" style={{ width: "100%" }}>
          <button type="button" style={{ flex: 1, justifyContent: "center" }} aria-selected={tab === "jobs"} onClick={() => setTab("jobs")}>Background work</button>
          <button type="button" style={{ flex: 1, justifyContent: "center" }} aria-selected={tab === "history"} onClick={() => setTab("history")}>History</button>
        </div>
      </div>
      <div className="scroll">{tab === "jobs" ? <Jobs /> : <History />}</div>
    </>
  );
}
