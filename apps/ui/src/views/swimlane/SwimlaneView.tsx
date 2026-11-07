/**
 * Swimlane: one lane per entity (or per type), dated claims placed along time.
 * Drag a chip sideways to change its date; drag it to another entity lane to move the fact to
 * that entity. Both are ordinary claim edits, so they are logged and undoable.
 */
import type { Claim } from "@folio/api-client";
import { scaleTime } from "d3-scale";
import { useEffect, useMemo, useRef, useState } from "react";
import { useKnowledgeActions, useSwimlane } from "@/api/queries";
import { TypeDot } from "@/components/Badges";
import { predicateLabel, shortDate, valueText } from "@/lib/format";
import { selectClaims, ui } from "@/state/selection";

const LANE_H = 46;
const NO_IDS: string[] = []; // stable reference: store selectors must not allocate
const TITLE_W = 180;

function toDate(iso: string): Date {
  return new Date(`${iso.slice(0, 10)}T00:00:00`);
}

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function SwimlaneView() {
  const [groupBy, setGroupBy] = useState<"entity" | "type">("entity");
  const { data } = useSwimlane(groupBy);
  const actions = useKnowledgeActions();
  const selected = ui.use((s) => (s.selection.kind === "claim" ? s.selection.ids : NO_IDS));
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number } | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.max(480, el.clientWidth - TITLE_W - 16)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const scale = useMemo(() => {
    const dates = (data?.lanes ?? []).flatMap((l) => l.items.map((i) => toDate(i.valid_from!)));
    const min = dates.length ? new Date(Math.min(...dates.map(Number))) : new Date();
    const max = dates.length ? new Date(Math.max(...dates.map(Number))) : new Date();
    const pad = Math.max(7 * 86400e3, (Number(max) - Number(min)) * 0.06);
    return scaleTime().domain([new Date(Number(min) - pad), new Date(Number(max) + pad)]).range([8, width - 160]); // leave room for the last chip's label
  }, [data, width]);

  if (!data) return <div className="empty">Loading…</div>;
  const lanes = data.lanes;

  const onPointerDown = (e: React.PointerEvent, c: Claim) => {
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const start = { x: e.clientX, y: e.clientY };
    setDrag({ id: c.id, dx: 0, dy: 0 });
    const move = (ev: PointerEvent) => setDrag({ id: c.id, dx: ev.clientX - start.x, dy: ev.clientY - start.y });
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDrag(null);
      const dx = ev.clientX - start.x;
      const dy = ev.clientY - start.y;
      if (Math.abs(dx) < 4 && Math.abs(dy) < 4) {
        selectClaims([c.id]);
        return;
      }
      const changes: Record<string, unknown> = {};
      const newDate = iso(scale.invert(scale(toDate(c.valid_from!)) + dx));
      if (Math.abs(dx) >= 4 && newDate !== c.valid_from) changes.valid_from = newDate;
      const laneShift = Math.round(dy / LANE_H);
      const from = lanes.findIndex((l) => l.items.some((i) => i.id === c.id));
      const to = from + laneShift;
      if (groupBy === "entity" && laneShift !== 0 && to >= 0 && to < lanes.length) changes.subject_id = lanes[to].id;
      if (Object.keys(changes).length) actions.editClaim.mutate({ id: c.id, changes });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className="view" style={{ display: "flex", flexDirection: "column" }}>
      <div className="toolbar">
        <span className="small muted">Lanes by</span>
        <button type="button" className="tab" aria-selected={groupBy === "entity"} onClick={() => setGroupBy("entity")}>Entity</button>
        <button type="button" className="tab" aria-selected={groupBy === "type"} onClick={() => setGroupBy("type")}>Type</button>
        <span className="spacer" />
        <span className="small muted">Drag a chip to change its date{groupBy === "entity" ? " or move it to another entity" : ""}</span>
      </div>
      <div className="scroll swim" ref={wrap}>
        {lanes.length === 0 && <div className="empty">No dated facts yet.</div>}
        {lanes.length > 0 && (
          <div style={{ minWidth: TITLE_W + width }}>
            <div className="axis">
              <div />
              <div className="axis-track">
                {scale.ticks(Math.max(2, Math.floor(width / 120))).map((t) => (
                  <span key={t.toISOString()} className="tick" style={{ left: scale(t) }}>{shortDate(t.toISOString())}</span>
                ))}
              </div>
            </div>
            {lanes.map((lane) => (
              <div key={lane.id} className="swim-lane" style={{ height: LANE_H }}>
                <div className="swim-title">
                  <TypeDot type={lane.type} />
                  <span className="ellipsis">{lane.title}</span>
                </div>
                <div className="swim-track">
                  {lane.items.map((c) => {
                    const dragging = drag?.id === c.id;
                    const label = c.kind === "relation" ? predicateLabel(c.predicate) : `${predicateLabel(c.predicate)}: ${valueText(c)}`;
                    return (
                      <div
                        key={c.id}
                        className={`chip ${c.status} ${dragging ? "dragging" : ""}`}
                        style={{
                          left: scale(toDate(c.valid_from!)) + (dragging ? drag.dx : 0),
                          top: 9 + (dragging ? drag.dy : 0),
                          outline: selected.includes(c.id) ? "2px solid var(--accent)" : undefined,
                        }}
                        title={`${shortDate(c.valid_from)} — ${label}`}
                        onPointerDown={(e) => onPointerDown(e, c)}
                      >
                        {label}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
