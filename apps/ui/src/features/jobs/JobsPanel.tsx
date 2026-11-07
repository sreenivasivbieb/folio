/** Job dashboard (NFR observability): any failed job shows its cause and can be retried. */
import { useState } from "react";
import { unwrap, useApi } from "@/api/client";
import { useAction, useJobs } from "@/api/queries";
import { useSourceNames } from "@/features/sources/useSourceNames";

const TONE: Record<string, string> = { done: "verified", failed: "rejected", running: "proposed", queued: "" };

export function JobsPanel() {
  const { client } = useApi();
  const { data: jobs } = useJobs();
  const names = useSourceNames();
  const [open, setOpen] = useState<string | null>(null);
  const retry = useAction(async (id: string) => unwrap(await client.POST("/api/jobs/{job_id}/retry", { params: { path: { job_id: id } } })), "Retrying");

  if (!jobs?.length) return <div className="empty">No jobs yet.</div>;
  return (
    <div className="scroll">
      {jobs.map((j) => (
        <div key={j.id} className="list-item" style={{ flexDirection: "column", alignItems: "stretch", gap: 4 }} onClick={() => setOpen(open === j.id ? null : j.id)}>
          <div className="row">
            <span className={`badge ${TONE[j.status] ?? ""}`}>{j.status}</span>
            <span className="small">{j.kind.replace("_source", "")}</span>
            <span className="ellipsis small muted" style={{ flex: 1 }}>{names[String(j.payload.source_id)] ?? ""}</span>
            {j.status === "failed" && (
              <button type="button" className="btn small" onClick={(e) => { e.stopPropagation(); retry.mutate(j.id); }}>Retry</button>
            )}
          </div>
          {j.status === "running" && <div className="progress"><div style={{ width: `${Math.round(j.progress * 100)}%` }} /></div>}
          {j.message && <div className="small muted">{j.message}</div>}
          {j.error && (open === j.id ? <pre className="mono" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{j.error}</pre> : <div className="small" style={{ color: "var(--bad)" }}>{j.error.split("\n")[0]}</div>)}
        </div>
      ))}
    </div>
  );
}
