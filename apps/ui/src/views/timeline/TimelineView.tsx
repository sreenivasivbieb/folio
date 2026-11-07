/** Timeline: one time axis of dated claims for one entity, like an activity feed. Edit a date,
 * reject an event, or open its source inline (ClaimRow). */
import type { Claim } from "@folio/api-client";
import { useTimeline } from "@/api/queries";
import { TypeDot } from "@/components/Badges";
import { ClaimRow, type EntityRef } from "@/features/claims/ClaimRow";
import { useSourceNames } from "@/features/sources/useSourceNames";
import { shortDate } from "@/lib/format";
import { ui } from "@/state/selection";

function monthKey(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "long" });
}

export function TimelineView() {
  const focus = ui.use((s) => s.focusEntity);
  const { data } = useTimeline(focus);
  const sources = useSourceNames();
  if (!focus) return <div className="empty">Select an entity (graph, search or card) to see its timeline.</div>;
  if (!data) return <div className="empty">Loading…</div>;
  const entities = data.entities as Record<string, EntityRef>;
  const months = new Map<string, Claim[]>();
  for (const item of data.items) {
    const key = monthKey(item.valid_from!);
    months.set(key, [...(months.get(key) ?? []), item]);
  }
  return (
    <div className="scroll">
      <div className="timeline">
        {data.entity && (
          <h2 className="row" style={{ margin: "0 0 8px" }}>
            <TypeDot type={data.entity.type} /> {data.entity.name}
            <span className="muted small" style={{ fontWeight: 400 }}>{data.items.length} dated facts</span>
          </h2>
        )}
        {data.items.length === 0 && <div className="empty">No dated facts yet for this entity.</div>}
        {[...months.entries()].map(([month, items]) => (
          <div key={month}>
            <div className="tl-month">{month}</div>
            {items.map((c) => (
              <div key={c.id} className="tl-item">
                <div className="tl-date">{shortDate(c.valid_from)}</div>
                <ClaimRow claim={c} entities={entities} sources={sources} selfId={focus ?? undefined} />
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
