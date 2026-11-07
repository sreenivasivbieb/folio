/** Ctrl+K: entity query by text. Entities first, then matching passages (hybrid search). */
import { useState } from "react";
import { useSearch } from "@/api/queries";
import { TypeDot } from "@/components/Badges";
import { Modal } from "@/components/Modal";
import { basename, locatorLabel } from "@/lib/format";
import { openEvidence, selectEntity, ui } from "@/state/selection";

export function SearchPalette() {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const { data } = useSearch(q);
  const entities = data?.entities ?? [];
  const passages = data?.passages ?? [];
  const close = () => ui.set({ modal: "none" });
  const pickEntity = (id: string) => {
    selectEntity(id);
    close();
  };

  return (
    <Modal title="Search" onClose={close}>
      <input
        className="input"
        style={{ width: "100%", fontSize: 15 }}
        autoFocus
        placeholder="Ask about an entity — “Acme”, “Priya”, “contract signed”…"
        value={q}
        onChange={(e) => { setQ(e.target.value); setActive(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((i) => Math.min(i + 1, entities.length - 1));
          if (e.key === "ArrowUp") setActive((i) => Math.max(i - 1, 0));
          if (e.key === "Enter" && entities[active]) pickEntity(entities[active].id);
        }}
      />
      {entities.length > 0 && <div className="small muted" style={{ margin: "10px 0 4px" }}>Entities</div>}
      {entities.map((e, i) => (
        <div key={e.id} className={`palette-item ${i === active ? "active" : ""}`} onClick={() => pickEntity(e.id)}>
          <TypeDot type={e.type} /> <b>{e.name}</b> <span className="muted small">{e.type}</span>
          <span className="spacer" />
          <span className={`badge ${e.status}`}>{e.status}</span>
        </div>
      ))}
      {passages.length > 0 && <div className="small muted" style={{ margin: "10px 0 4px" }}>Passages</div>}
      {passages.map((p) => (
        <div
          key={p.chunk_id}
          className="palette-item"
          style={{ flexDirection: "column", alignItems: "flex-start", gap: 2 }}
          onClick={() => {
            openEvidence({ id: p.chunk_id, claim_id: "", source_id: p.source_id, chunk_id: p.chunk_id, locator: p.locator as never, quote: p.text.slice(0, 160) });
            close();
          }}
        >
          <span className="small muted">{basename(p.path)} · {locatorLabel(p.locator as never)}</span>
          <span className="small">{p.text.slice(0, 200)}{p.text.length > 200 ? "…" : ""}</span>
        </div>
      ))}
      {q.length > 1 && data && !entities.length && !passages.length && <div className="empty">No matches.</div>}
    </Modal>
  );
}
