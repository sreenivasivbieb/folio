/** The user sees a preview and confirms or cancels; ambiguity is a question, never a guess. */
import type { Label } from "@folio/api-client";
import { useEffect, useState } from "react";
import type { useLabelActions } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { Modal } from "@/components/Modal";

/** Mirror of the core's label plan (speech/label_parser.py). */
interface LabelPlan {
  preview: string[];
  questions: { id: string; text: string; field: "type" | "entity_id"; options: { label: string; value: string }[] }[];
  unparsed: string[];
  ops: unknown[];
}

function OtherType({ onPick }: { onPick: (v: string) => void }) {
  const [v, setV] = useState("");
  return (
    <span className="row">
      <input className="input" style={{ width: 150, height: 26 }} placeholder="Other type…" value={v} onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && v.trim()) onPick(v.trim()); }} />
      <button type="button" className="btn sm" disabled={!v.trim()} onClick={() => onPick(v.trim())}>Use</button>
    </span>
  );
}

export function LabelPreview({ label, actions }: { label: Label; actions: ReturnType<typeof useLabelActions> }) {
  const plan = label.parsed as unknown as LabelPlan;
  const ready = plan.questions.length === 0 && plan.ops.length > 0;
  const answer = (q: string, value: string) => actions.answer.mutate({ id: label.id, question: q, value });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter" && ready && !(e.target as HTMLElement).closest("input")) actions.confirm.mutate(label.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ready, label.id, actions.confirm]);

  return (
    <Modal
      title={<><Icon name={label.audio_path ? "mic" : "pencil"} /> Review label</>}
      onClose={() => actions.cancel.mutate(label.id)}
      footer={
        <>
          <span className="small muted" style={{ marginRight: "auto" }}>Nothing is saved until you confirm · one Ctrl+Z undoes it all</span>
          <button type="button" className="btn" onClick={() => actions.cancel.mutate(label.id)}>Cancel</button>
          <button type="button" className="btn primary" disabled={!ready} onClick={() => actions.confirm.mutate(label.id)}>
            <Icon name="check" /> Confirm <span className="kbd" style={{ background: "transparent", color: "inherit", borderColor: "currentColor" }}>Enter</span>
          </button>
        </>
      }
    >
      <div className="row" style={{ alignItems: "flex-start", gap: 10, marginBottom: 14 }}>
        <Icon name="quote" size={16} className="muted" style={{ marginTop: 2 }} />
        <div style={{ fontSize: 14, lineHeight: 1.5 }}>{label.transcript}</div>
      </div>
      {plan.preview.map((line) => (
        <div key={line} className="preview-line"><Icon name="plus" size={13} style={{ color: "var(--ok)" }} />{line}</div>
      ))}
      {plan.questions.map((q) => (
        <div key={q.id} className="question">
          <div className="row" style={{ marginBottom: 8, fontWeight: 550 }}><Icon name="info" size={14} />{q.text}</div>
          <div className="row wrap">
            {q.options.map((o) => (
              <button type="button" key={o.value} className="btn sm" onClick={() => answer(q.id, o.value)}>{o.label}</button>
            ))}
            {q.field === "type" && <OtherType onPick={(v) => answer(q.id, v)} />}
          </div>
        </div>
      ))}
      {plan.unparsed.length > 0 && (
        <div className="callout warn" style={{ marginTop: 10 }}>
          <Icon name="alert" />
          <span>Not understood, will be ignored: {plan.unparsed.map((u) => `“${u}”`).join(", ")}</span>
        </div>
      )}
      {plan.ops.length === 0 && (
        <div className="callout" style={{ marginTop: 10 }}>
          <Icon name="info" />
          <span>Nothing to apply. Try “this is the Acme contract”, “Priya owns it”, “signed March 3”, “it is a Course”, “this is wrong”, “merge these two”.</span>
        </div>
      )}
    </Modal>
  );
}
