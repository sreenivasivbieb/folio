/** Add a user-asserted fact. Open schema: any attribute or relation name; hints are suggestions. */
import type { Entity } from "@folio/api-client";
import { useState } from "react";
import { useEntities, useKnowledgeActions } from "@/api/queries";
import { TypePill } from "@/components/Badges";
import { Icon } from "@/components/Icon";
import { predicatesFor, useSchemaDef } from "@/lib/schema";

export function AddFact({ entity }: { entity: Entity }) {
  const schema = useSchemaDef();
  const actions = useKnowledgeActions();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"attribute" | "relation">("attribute");
  const [predicate, setPredicate] = useState("");
  const [value, setValue] = useState("");
  const [query, setQuery] = useState("");
  const { attributes, relations } = predicatesFor(schema, entity.type);
  const attrType = attributes.find(([n]) => n === predicate)?.[1]?.type;
  const { data: candidates } = useEntities(query);

  const reset = () => {
    setOpen(false);
    setPredicate("");
    setValue("");
    setQuery("");
  };
  if (!open) {
    return <button type="button" className="btn sm ghost" onClick={() => setOpen(true)}><Icon name="plus" size={13} /> Add a fact</button>;
  }
  const saveAttribute = () => {
    if (!predicate.trim() || !value.trim()) return;
    actions.createClaim.mutate({ subject_id: entity.id, predicate, value, valid_from: attrType === "date" ? value : null });
    reset();
  };

  return (
    <div className="stack" style={{ marginTop: 8, padding: 10, background: "var(--surface-2)", borderRadius: 10 }}>
      <div className="seg">
        <button type="button" aria-selected={mode === "attribute"} onClick={() => setMode("attribute")}>Value</button>
        <button type="button" aria-selected={mode === "relation"} onClick={() => setMode("relation")}>Link to entity</button>
      </div>
      <input className="input" list="fact-predicates" autoFocus value={predicate} onChange={(e) => setPredicate(e.target.value)}
        placeholder={mode === "attribute" ? "e.g. email, role, deadline, semester" : "e.g. teaches, part_of, works_at"} />
      <datalist id="fact-predicates">
        {(mode === "attribute" ? attributes : relations).map(([n]) => <option key={n} value={n} />)}
      </datalist>
      {mode === "attribute" ? (
        <input className="input" type={attrType === "date" ? "date" : "text"} placeholder="value" value={value}
          onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && saveAttribute()} />
      ) : (
        <>
          <input className="input" placeholder="Find the other entity…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <div style={{ maxHeight: 170, overflow: "auto" }}>
            {(candidates ?? []).filter((c) => c.id !== entity.id).slice(0, 8).map((c) => (
              <div key={c.id} className="palette-item" onClick={() => {
                if (!predicate.trim()) return;
                actions.createClaim.mutate({ subject_id: entity.id, predicate, object_id: c.id });
                reset();
              }}>
                <span className="grow ellipsis">{c.name}</span><TypePill type={c.type} />
              </div>
            ))}
          </div>
          {!predicate.trim() && <span className="tiny muted">Name the relation first, then pick the entity.</span>}
        </>
      )}
      <div className="row">
        <span className="spacer" />
        <button type="button" className="btn sm ghost" onClick={reset}>Cancel</button>
        {mode === "attribute" && <button type="button" className="btn sm primary" disabled={!predicate.trim() || !value.trim()} onClick={saveAttribute}>Add</button>}
      </div>
    </div>
  );
}
