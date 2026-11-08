/** Ctrl+K: entity query by text. Entities first, then matching passages (hybrid search). */
import { useState } from "react";
import { useSearch } from "@/api/queries";
import { TypePill } from "@/components/Badges";
import { Icon } from "@/components/Icon";
import { Modal } from "@/components/Modal";
import { basename, locatorLabel } from "@/lib/format";
import { openEvidence, selectEntity, ui } from "@/state/selection";

export function SearchPalette() {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const { data, isFetching } = useSearch(q);
  const entities = data?.entities ?? [];
  const passages = data?.passages ?? [];
  const close = () => ui.set({ modal: "none" });
  const pickEntity = (id: string) => {
    selectEntity(id);
    close();
  };

  return (
    <Modal onClose={close} bare>
      <div className="palette-input">
        <Icon name={isFetching ? "loader" : "search"} spin={isFetching} size={18} className="muted" />
        <input
          autoFocus
          placeholder="Search people, topics, organisations, passages…"
          value={q}
          onChange={(e) => { setQ(e.target.value); setActive(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") setActive((i) => Math.min(i + 1, entities.length - 1));
            if (e.key === "ArrowUp") setActive((i) => Math.max(i - 1, 0));
            if (e.key === "Enter" && entities[active]) pickEntity(entities[active].id);
          }}
        />
        <span className="kbd">Esc</span>
      </div>
      <div style={{ overflow: "auto", maxHeight: "60vh" }}>
        {q.trim().length < 2 && <div className="empty-inline">Type at least two characters. Results come from entity names and the full text of every file.</div>}
        {entities.length > 0 && (
          <div className="palette-group">
            <div className="label">Entities</div>
            {entities.map((e, i) => (
              <div key={e.id} className={`palette-item ${i === active ? "active" : ""}`} onClick={() => pickEntity(e.id)} onMouseEnter={() => setActive(i)}>
                <b className="grow ellipsis">{e.name}</b>
                <TypePill type={e.type} />
                {e.status !== "verified" && <span className={`badge ${e.status}`}>{e.status}</span>}
              </div>
            ))}
          </div>
        )}
        {passages.length > 0 && (
          <div className="palette-group">
            <div className="label">Passages</div>
            {passages.map((p) => (
              <div key={p.chunk_id} className="palette-item" style={{ alignItems: "flex-start" }}
                onClick={() => {
                  openEvidence({ id: p.chunk_id, claim_id: "", source_id: p.source_id, chunk_id: p.chunk_id, locator: p.locator as never, quote: p.text.slice(0, 160) });
                  close();
                }}>
                <Icon name="quote" size={14} className="muted" style={{ marginTop: 2 }} />
                <div className="grow">
                  <div className="tiny muted">{basename(p.path)} · {locatorLabel(p.locator as never)}</div>
                  <div className="small">{p.text.slice(0, 220)}{p.text.length > 220 ? "…" : ""}</div>
                </div>
              </div>
            ))}
          </div>
        )}
        {q.trim().length > 1 && data && !entities.length && !passages.length && <div className="empty-inline">No matches.</div>}
      </div>
    </Modal>
  );
}
