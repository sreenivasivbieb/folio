/** FR-10: every claim can show its full history — who or what made it, with which model and
 * prompt version, and each later change. */
import { useClaimHistory } from "@/api/queries";

const SKIP = new Set(["updated_at", "evidence", "fingerprint"]);

export function ClaimHistory({ claimId }: { claimId: string }) {
  const { data } = useClaimHistory(claimId);
  if (!data) return null;
  return (
    <div className="stack" style={{ gap: 4, marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--border)" }}>
      {data.map((h) => {
        const after = (h.after ?? {}) as Record<string, unknown>;
        const before = (h.before ?? {}) as Record<string, unknown>;
        const changed = h.op === "update" ? Object.keys(after).filter((k) => !SKIP.has(k) && JSON.stringify(after[k]) !== JSON.stringify(before[k])) : [];
        const extractor = after.extractor as { model?: string; prompt_version?: string } | undefined;
        return (
          <div key={h.seq} className="tiny" style={{ display: "grid", gridTemplateColumns: "118px 1fr", gap: 8 }}>
            <span className="mono muted">{new Date(h.ts).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}</span>
            <span>
              <span className="badge" style={{ height: 17 }}>{h.actor.startsWith("model:") ? "AI" : h.actor}</span>{" "}
              {h.op === "insert" && <>created{extractor?.model ? <> by <span className="mono">{extractor.model}</span>{extractor.prompt_version ? ` (${extractor.prompt_version})` : ""}</> : ""}</>}
              {h.op === "update" && (changed.map((k) => `${k}: ${String(before[k])} → ${String(after[k])}`).join(", ") || "evidence updated")}
              {h.op === "delete" && "deleted"}
              {h.action === "undo" || h.action === "redo" ? <span className="muted"> ({h.action})</span> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}
