/** The user sees a preview and confirms or cancels; ambiguity is a question, never a guess. */
import type { Label } from "@folio/api-client";
import { useEffect } from "react";
import type { useLabelActions } from "@/api/queries";
import { Modal } from "@/components/Modal";

/** Mirror of the core's label plan (speech/label_parser.py). */
interface LabelPlan {
  preview: string[];
  questions: { id: string; text: string; options: { label: string; value: string }[] }[];
  unparsed: string[];
  ops: unknown[];
}

export function LabelPreview({ label, actions }: { label: Label; actions: ReturnType<typeof useLabelActions> }) {
  const plan = label.parsed as unknown as LabelPlan;
  const ready = plan.questions.length === 0 && plan.ops.length > 0;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter" && ready && !(e.target as HTMLElement).closest("input")) actions.confirm.mutate(label.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ready, label.id, actions.confirm]);

  return (
    <Modal
      title={<>Label preview {label.audio_path && <span className="badge">voice</span>}</>}
      onClose={() => actions.cancel.mutate(label.id)}
      footer={
        <>
          <span className="small muted" style={{ marginRight: "auto" }}>Nothing is saved until you confirm. One Ctrl+Z undoes it all.</span>
          <button type="button" className="btn" onClick={() => actions.cancel.mutate(label.id)}>Cancel (Esc)</button>
          <button type="button" className="btn primary" disabled={!ready} onClick={() => actions.confirm.mutate(label.id)}>Confirm (Enter)</button>
        </>
      }
    >
      <div className="excerpt" style={{ marginBottom: 10 }}>“{label.transcript}”</div>
      {plan.preview.map((line) => <div key={line} className="preview-line">{line}</div>)}
      {plan.questions.map((q) => (
        <div key={q.id} className="question">
          <div style={{ marginBottom: 6 }}>{q.text}</div>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {q.options.map((o) => (
              <button type="button" key={o.value} className="btn small" onClick={() => actions.answer.mutate({ id: label.id, question: q.id, value: o.value })}>
                {o.label}
              </button>
            ))}
          </div>
        </div>
      ))}
      {plan.unparsed.length > 0 && (
        <div className="small" style={{ color: "var(--warn)", marginTop: 8 }}>
          Not understood (ignored): {plan.unparsed.map((u) => `“${u}”`).join(", ")}
        </div>
      )}
      {plan.ops.length === 0 && <div className="muted">Nothing to apply. Try e.g. “this is the Acme contract”, “Priya owns it”, “signed March 3”, “this is wrong”, “merge these two”.</div>}
    </Modal>
  );
}
