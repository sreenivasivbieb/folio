/** Add a user-asserted fact: an attribute value or a relation to another entity (schema-driven). */
import type { Entity } from "@folio/api-client";
import { useState } from "react";
import { useEntities, useKnowledgeActions } from "@/api/queries";
import { predicateLabel } from "@/lib/format";
import { predicatesFor, useSchemaDef } from "@/lib/schema";

export function AddFact({ entity }: { entity: Entity }) {
  const schema = useSchemaDef();
  const actions = useKnowledgeActions();
  const [open, setOpen] = useState(false);
  const [predicate, setPredicate] = useState("");
  const [value, setValue] = useState("");
  const [objectQuery, setObjectQuery] = useState("");
  const { attributes, relations } = predicatesFor(schema, entity.type);
  const relation = relations.find(([n]) => n === predicate)?.[1];
  const attribute = attributes.find(([n]) => n === predicate)?.[1];
  const targets = relation ? (relation.target.includes("*") ? undefined : relation.target) : undefined;
  const { data: candidates } = useEntities(objectQuery, targets);

  if (!open) {
    return <button type="button" className="btn small" onClick={() => setOpen(true)}>+ Add fact</button>;
  }
  const reset = () => {
    setOpen(false);
    setPredicate("");
    setValue("");
    setObjectQuery("");
  };
  return (
    <div className="stack" style={{ marginTop: 8, padding: 8, background: "var(--panel-2)", borderRadius: 8 }}>
      <select className="input" value={predicate} onChange={(e) => setPredicate(e.target.value)} autoFocus>
        <option value="">Choose attribute or relation…</option>
        <optgroup label="Attributes">
          {attributes.map(([n, a]) => <option key={n} value={n}>{predicateLabel(n)} ({a.type})</option>)}
        </optgroup>
        <optgroup label="Relations">
          {relations.map(([n, r]) => <option key={n} value={n}>{predicateLabel(n)} → {r.target.join(" | ")}</option>)}
        </optgroup>
      </select>
      {attribute && (
        <input
          className="input"
          type={attribute.type === "date" ? "date" : "text"}
          placeholder={attribute.type}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && value) {
              actions.createClaim.mutate({ subject_id: entity.id, predicate, value, valid_from: attribute.type === "date" ? value : null });
              reset();
            }
          }}
        />
      )}
      {relation && (
        <>
          <input className="input" placeholder="Find entity…" value={objectQuery} onChange={(e) => setObjectQuery(e.target.value)} />
          <div style={{ maxHeight: 160, overflow: "auto" }}>
            {(candidates ?? []).filter((c) => c.id !== entity.id).slice(0, 8).map((c) => (
              <div
                key={c.id}
                className="palette-item"
                onClick={() => {
                  actions.createClaim.mutate({ subject_id: entity.id, predicate, object_id: c.id });
                  reset();
                }}
              >
                {c.name} <span className="muted small">{c.type}</span>
              </div>
            ))}
          </div>
        </>
      )}
      <div className="row">
        <span className="spacer" />
        <button type="button" className="btn small" onClick={reset}>Cancel</button>
      </div>
    </div>
  );
}
