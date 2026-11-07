/**
 * Voice-first labeling (FR-3). Hold the mic button (or Ctrl+Space) and speak; release to see a
 * preview. Typing a label goes through exactly the same pipeline. The target is whatever is
 * selected: a file, entities, or claims ("this is wrong, the owner is Priya").
 */
import { useEffect, useState } from "react";
import { inTauri } from "@/api/connection";
import { useLabelActions, useSources, useStatus } from "@/api/queries";
import { basename } from "@/lib/format";
import { labelTarget, type Selection, ui } from "@/state/selection";
import { LabelPreview } from "./LabelPreview";

function describe(sel: Selection, sourceName: (id: string) => string): string {
  switch (sel.kind) {
    case "source":
      return `file: ${sourceName(sel.id)}`;
    case "entity":
      return sel.ids.length === 1 ? "1 entity" : `${sel.ids.length} entities`;
    case "claim":
      return sel.ids.length === 1 ? "1 fact" : `${sel.ids.length} facts`;
    default:
      return "nothing selected";
  }
}

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

  const start = () => {
    if (!canSpeak || recording) return;
    ui.set({ recording: true });
    actions.start.mutate(labelTarget(ui.get().selection), { onError: () => ui.set({ recording: false }) });
  };
  const stop = () => {
    if (!ui.get().recording) return;
    ui.set({ recording: false });
    actions.stop.mutate(undefined);
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

  const micTitle = canSpeak
    ? "Hold to talk (Ctrl+Space)"
    : voice
      ? `Voice unavailable: ${voice.speech_available ? voice.microphone_detail : "no speech model installed"} — type the label instead`
      : "";

  return (
    <div className="voicebar">
      <button
        type="button"
        className={`ptt ${recording ? "recording" : ""}`}
        disabled={!canSpeak}
        title={micTitle}
        onPointerDown={start}
        onPointerUp={stop}
        onPointerLeave={stop}
        aria-label="Push to talk"
      >
        🎙
      </button>
      <span className="target" title="Labels apply to the current selection">→ {describe(selection, sourceName)}</span>
      <input
        className="input"
        style={{ flex: 1 }}
        placeholder={recording ? "Listening… release to preview" : "Type a label — e.g. “This PDF is the Acme contract, Priya owns it, signed March 3”"}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && text.trim()) {
            actions.typed.mutate({ transcript: text.trim(), target: labelTarget(selection) });
            setText("");
          }
        }}
      />
      <span className="kbd">Enter</span>
      {label && <LabelPreview label={label} actions={actions} />}
    </div>
  );
}
