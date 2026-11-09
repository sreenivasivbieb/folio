/** Ctrl+K or "/": one box for everything — files (names, descriptions, labels), people and topics,
 * and passages inside files. Suggestions before typing; arrow keys move through all results. */
import { Fragment, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useSearch } from "@/api/queries";
import { TypePill } from "@/components/Badges";
import { Icon, kindIcon } from "@/components/Icon";
import { Modal } from "@/components/Modal";
import { basename, locatorLabel } from "@/lib/format";
import { openEvidence, selectEntity, selectSource, ui } from "@/state/selection";

/** Wrap the typed words in <mark> (case-insensitive). */
function highlight(text: string, q: string): ReactNode {
  const words = q.trim().split(/\s+/).filter((w) => w.length > 1).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return text;
  const parts = text.split(new RegExp(`(${words.join("|")})`, "ig"));
  return parts.map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : <Fragment key={i}>{p}</Fragment>));
}

type Item = { key: string; group: string; open: () => void; render: (active: boolean) => ReactNode };

export function SearchPalette() {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const { data, isFetching } = useSearch(q);
  const close = () => ui.set({ modal: "none" });
  const typed = q.trim().length > 1;
  const list = useRef<HTMLDivElement>(null);

  const items = useMemo<Item[]>(() => {
    const out: Item[] = [];
    for (const f of data?.files ?? []) {
      out.push({
        key: `f:${f.source_id}`, group: typed ? "Files" : "Recent files",
        open: () => { selectSource(f.source_id); close(); },
        render: () => (
          <>
            <span className="palette-icon"><Icon name={kindIcon(f.kind)} size={14} /></span>
            <div className="grow" style={{ minWidth: 0 }}>
              <div className="ellipsis"><b>{highlight(basename(f.path), q)}</b></div>
              {typed && f.via !== "file name" && <div className="tiny muted ellipsis">{highlight(f.via, q)}</div>}
            </div>
            {f.status !== "indexed" && <span className={`badge ${f.status}`}>{f.status}</span>}
          </>
        ),
      });
    }
    for (const e of data?.entities ?? []) {
      out.push({
        key: `e:${e.id}`, group: typed ? "People, topics & more" : "In your knowledge",
        open: () => { selectEntity(e.id); close(); },
        render: () => (
          <>
            <span className="palette-icon"><Icon name="graph" size={14} /></span>
            <b className="grow ellipsis">{highlight(e.name, q)}</b>
            <TypePill type={e.type} />
          </>
        ),
      });
    }
    for (const p of data?.passages ?? []) {
      out.push({
        key: `p:${p.chunk_id}`, group: "Inside files",
        open: () => {
          openEvidence({ id: p.chunk_id, claim_id: "", source_id: p.source_id, chunk_id: p.chunk_id, locator: p.locator as never, quote: p.text.slice(0, 160) });
          close();
        },
        render: () => (
          <>
            <span className="palette-icon"><Icon name="quote" size={14} /></span>
            <div className="grow" style={{ minWidth: 0 }}>
              <div className="tiny muted ellipsis">{basename(p.path)} · {locatorLabel(p.locator as never)}</div>
              <div className="small palette-snippet">{highlight(p.text.slice(0, 220), q)}{p.text.length > 220 ? "…" : ""}</div>
            </div>
          </>
        ),
      });
    }
    return out;
  }, [data, q, typed]);

  useEffect(() => setActive(0), [q]);
  useEffect(() => {
    list.current?.querySelector(".palette-item.active")?.scrollIntoView({ block: "nearest" });
  }, [active]);

  let lastGroup = "";
  return (
    <Modal onClose={close} bare>
      <div className="palette-input">
        <Icon name={isFetching ? "loader" : "search"} spin={isFetching} size={18} className="muted" />
        <input
          autoFocus
          placeholder="Search files, descriptions, people, topics and text…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, items.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
            if (e.key === "Enter" && items[active]) items[active].open();
          }}
        />
        <span className="kbd">Esc</span>
      </div>
      <div ref={list} style={{ overflow: "auto", maxHeight: "62vh", paddingBottom: 6 }}>
        {items.map((it, i) => {
          const header = it.group !== lastGroup ? it.group : null;
          lastGroup = it.group;
          return (
            <Fragment key={it.key}>
              {header && <div className="palette-group"><div className="label">{header}</div></div>}
              <div className={`palette-item ${i === active ? "active" : ""}`} onClick={it.open} onMouseEnter={() => setActive(i)}>
                {it.render(i === active)}
              </div>
            </Fragment>
          );
        })}
        {!items.length && !isFetching && (
          <div className="empty-inline">
            {typed ? <>No matches for “{q.trim()}”. Partial words and small typos are fine — try fewer words.</> : "Add files to Folio to search them here."}
          </div>
        )}
      </div>
      <div className="palette-foot tiny muted">
        <span><span className="kbd">↑</span><span className="kbd">↓</span> move</span>
        <span><span className="kbd">Enter</span> open</span>
        <span>Searches names, descriptions, labels and the text inside files</span>
      </div>
    </Modal>
  );
}
