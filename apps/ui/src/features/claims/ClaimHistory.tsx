/** FR-10: every claim can show its full history — who or what made it, with which model and
 * prompt version, and each later change. */
import { useClaimHistory } from "@/api/queries";

export function ClaimHistory({ claimId }: { claimId: string }) {
  const { data } = useClaimHistory(claimId);
  if (!data) return null;
  return (
    <div className="small" style={{ marginTop: 6, borderTop: "1px solid var(--border)", paddingTop: 6 }}>
      {data.map((h) => {
        const after = (h.after ?? {}) as Record<string, unknown>;
        const before = (h.before ?? {}) as Record<string, unknown>;
        const changed = h.op === "update" ? Object.keys(after).filter((k) => k !== "updated_at" && after[k] !== before[k]) : [];
        return (
          <div key={h.seq} className="row" style={{ alignItems: "baseline" }}>
            <span className="mono muted">{new Date(h.ts).toLocaleString()}</span>
            <span className="badge">{h.actor}</span>
            <span>{h.action}</span>
            <span className="muted">{h.op === "update" ? changed.map((k) => `${k}: ${String(before[k])} → ${String(after[k])}`).join(", ") : h.op}</span>
          </div>
        );
      })}
    </div>
  );
}
