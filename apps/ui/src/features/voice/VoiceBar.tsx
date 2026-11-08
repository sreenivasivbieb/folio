/**
 * Voice-first labeling (FR-3), as a composer. Hold the mic (or Ctrl+Space) and speak; release to
 * preview. Typing goes through exactly the same pipeline. The target is the current selection: a
 * file, entities, or facts ("this is wrong, the owner is Priya").
 */
import { useEffect, useState } from "react";
import { inTauri } from "@/api/connection";
import { useLabelActions, useSources, useStatus } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { basename } from "@/lib/format";
import { labelTarget, openSettings, type Selection, ui } from "@/state/selection";
import { LabelPreview } from "./LabelPreview";

function describe(sel: Selection, sourceName: (id: string) => string): string | null {
  switch (sel.kind) {
    case "source":
      return sourceName(sel.id);
    case "entity":
      return sel.ids.length === 1 ? "1 entity" : `${sel.ids.length} entities`;
    case "claim":
      return sel.ids.length === 1 ? "1 fact" : `${sel.ids.length} facts`;
    default:
      return null;
  }
}

const EXAMPLES: Record<Selection["kind"], string> = {
  source: "This PDF is the Acme contract, Priya owns it, signed March 3",
  entity: "Priya leads it · it is a Course · merge these two",
  claim: "This is wrong, the owner is Priya",
  none: "Select a file, entity or fact — then say or type what it is",
};

export function VoiceBar() {
  const selection = ui.use((s) => s.selection);
  const label = ui.use((s) => s.label);
  const recording = ui.use((s) => s.recording);
  const { data: status } = useStatus();
  const { data: sources } = useSources();
  const [text, setText] = useState("");
  const actions = useLabelActions((l) => ui.set({ label: l }));
  const voice = status?.voice;
  const canSpeak = !!voice?.speech_available && !!voice?.microphone;
  const sourceName = (id: string) => basename(sources?.find((s) => s.id === id)?.path ?? id);
  const target = describe(selection, sourceName);

  const start = () => {
    if (!canSpeak || ui.get().recording) return;
    ui.set({ recording: true });
    actions.start.mutate(labelTarget(ui.get().selection), { onError: () => ui.set({ recording: false }) });
  };
  const stop = () => {
    if (!ui.get().recording) return;
    ui.set({ recording: false });
    actions.stop.mutate(undefined);
  };
  const submit = () => {
    if (!text.trim()) return;
    actions.typed.mutate({ transcript: text.trim(), target: labelTarget(selection) });
    setText("");
  };

  // Global hotkey (Ctrl+Alt+Space) from the desktop shell: hold to talk even when unfocused.
  useEffect(() => {
    if (!inTauri) return;
    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/event").then(({ listen }) =>
      listen<boolean>("folio://push-to-talk", (e) => (e.payload ? start() : stop())).then((u) => {
        unlisten = u;
      }),
    );
    return () => unlisten?.();
  });

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.code === "Space" && !e.repeat) {
        e.preventDefault();
        start();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space" || e.key === "Control") stop();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  });

  return (
    <div className="voice">
      <div className="composer">
        <button
          type="button"
          className={`ptt ${recording ? "recording" : ""}`}
          disabled={!canSpeak}
          title={canSpeak ? "Hold to talk (Ctrl+Space)" : "Voice is not set up — open Settings → Voice"}
          onPointerDown={start}
          onPointerUp={stop}
          onPointerLeave={stop}
          aria-label="Push to talk"
        >
          <Icon name="mic" size={17} />
        </button>
        <span className={`target-chip ${target ? "set" : ""}`} title="Labels apply to the current selection">
          <Icon name={selection.kind === "source" ? "file" : selection.kind === "none" ? "info" : "layers"} size={12} />
          <span className="ellipsis">{target ?? "Nothing selected"}</span>
        </span>
        <input
          placeholder={recording ? "Listening… release to preview" : EXAMPLES[selection.kind]}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          aria-label="Type a label"
        />
        <button type="button" className="btn primary icon-only" disabled={!text.trim() || actions.typed.isPending} onClick={submit} title="Preview label (Enter)">
          {actions.typed.isPending ? <Icon name="loader" spin /> : <Icon name="send" />}
        </button>
      </div>
      <div className="composer-hint">
        {canSpeak
          ? <span>Hold <span className="kbd">Ctrl</span> <span className="kbd">Space</span> to talk</span>
          : <button type="button" className="btn ghost sm" onClick={() => openSettings("voice")}><Icon name="mic" size={12} /> Set up voice</button>}
        <span>Nothing is saved until you confirm the preview</span>
        <span><span className="kbd">Ctrl</span> <span className="kbd">Z</span> undoes anything</span>
      </div>
      {label && <LabelPreview label={label} actions={actions} />}
    </div>
  );
}
