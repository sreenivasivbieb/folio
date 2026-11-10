/** Drop & Label: drop files or a project folder, say or type what they are, let the AI organize. */
import type { Drop } from "@folio/api-client";
import { useEffect, useRef, useState } from "react";
import { useDrop, useDropActions, useDropPreview, useDrops, useStatus } from "@/api/queries";
import { Icon, kindIcon } from "@/components/Icon";
import { basename, shortDate } from "@/lib/format";
import { openProject, selectEntity, ui } from "@/state/selection";
import { type Mode, ModeChoice } from "@/features/vault/ModeChoice";
import { pickPaths } from "@/features/vault/pick";
import { groupByFolder } from "@/lib/drops";

export function DropView() {
  const active = ui.use((s) => s.activeDrop);
  return (
    <div className="scroll drop-view">
      {active ? <LabelCard dropId={active} /> : <Intake />}
      <RecentDrops />
    </div>
  );
}

function Intake() {
  const paths = ui.use((s) => s.pendingPaths);
  const [mode, setMode] = useState<Mode | null>(null);
  const { data: counts, isFetching, error } = useDropPreview(paths);
  const { create } = useDropActions();
  const pick = async (directory: boolean) => {
    const picked = await pickPaths(directory);
    if (picked.length) ui.set({ pendingPaths: Array.from(new Set([...ui.get().pendingPaths, ...picked])) });
  };
  const add = () => {
    if (!mode || !paths.length) return;
    create.mutate({ paths, mode }, { onSuccess: (d) => d && ui.set({ activeDrop: d.id, pendingPaths: [] }) });
  };
  return (
    <section className="drop-hero">
      <span className="tag-pill"><b>Drop</b>then label it in your own words</span>
      <h1 className="drop-title">Drop it, <b>say what it is</b>, done.</h1>
      <p className="drop-sub">Files or a whole project folder. Folio skips junk like node_modules, build output and binaries, then the AI organizes everything from your label.</p>
      <div className={`drop-target ${paths.length ? "has-files" : ""}`}>
        <Icon name="download" size={26} />
        <b>Drop files or a project folder anywhere on this window</b>
        <div className="row" style={{ justifyContent: "center" }}>
          <button type="button" className="btn" onClick={() => void pick(false)}><Icon name="file" /> Choose files</button>
          <button type="button" className="btn" onClick={() => void pick(true)}><Icon name="folder" /> Choose a folder</button>
        </div>
      </div>
      {!!paths.length && (
        <div className="drop-card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="ellipsis">
              {paths.map((p) => <span key={p} className="chip-path" title={p}><Icon name="folder" size={12} /> {basename(p)}</span>)}
            </div>
            <button type="button" className="btn ghost sm" onClick={() => ui.set({ pendingPaths: [] })}>Clear</button>
          </div>
          <div className="drop-counts">
            {isFetching ? "Counting files…"
              : error ? <span style={{ color: "var(--bad)" }}>{(error as Error).message}</span>
              : counts && <><b>{counts.files}</b> file{counts.files === 1 ? "" : "s"} to add{counts.skipped ? <span className="muted"> · {counts.skipped} junk file{counts.skipped === 1 ? "" : "s"} skipped</span> : null}</>}
          </div>
          <div className="field-label">Keep the originals where they are?</div>
          <ModeChoice value={mode} onChange={setMode}
            move="Files live only in Folio — no extra disk space. Export them back anytime."
            copy="Originals stay put; Folio keeps a copy. Needed for “Organize on disk”." />
          <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
            <button type="button" className="btn primary" disabled={!mode || !counts?.files || create.isPending} onClick={add}>
              {create.isPending ? <Icon name="loader" spin /> : <Icon name="plus" />} Add {counts?.files ?? ""} file{counts?.files === 1 ? "" : "s"} and label
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function LabelCard({ dropId }: { dropId: string }) {
  const { data: drop } = useDrop(dropId);
  const { data: status } = useStatus();
  const a = useDropActions();
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const voice = status?.voice;
  const canSpeak = !!voice?.speech_available && !!voice?.microphone;
  useEffect(() => { if (drop?.label && !text) setText(drop.label); }, [drop?.label]);
  useEffect(() => { box.current?.focus(); }, [dropId, !!drop]); // the box appears once the drop has loaded

  const startTalk = () => {
    if (!canSpeak || recording) return;
    setRecording(true);
    a.voiceStart.mutate(undefined, { onError: () => setRecording(false) });
  };
  const stopTalk = () => {
    if (!recording) return;
    setRecording(false);
    a.voiceText.mutate(undefined, {
      onSuccess: (r) => { if (r?.transcript) setText((t) => (t ? `${t} ${r.transcript}` : r.transcript)); box.current?.focus(); },
    });
  };
  const organize = () => text.trim() && a.label.mutate({ id: dropId, text: text.trim() });

  // Hold Ctrl+Space anywhere on this screen to speak the label (same as the button).
  const talk = useRef({ startTalk, stopTalk });
  talk.current = { startTalk, stopTalk };
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.code === "Space" && !e.repeat) { e.preventDefault(); talk.current.startTalk(); }
    };
    const up = (e: KeyboardEvent) => { if (e.code === "Space" || e.key === "Control") talk.current.stopTalk(); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, []);
  if (!drop) return <section className="drop-hero"><Icon name="loader" spin /></section>;
  const busy = drop.status === "organizing" || (drop.status === "importing" && !!drop.label);

  return (
    <section className="drop-hero">
      <div className="row" style={{ justifyContent: "space-between", width: "100%", maxWidth: 760 }}>
        <span className="tag-pill"><b>{drop.file_count} file{drop.file_count === 1 ? "" : "s"}</b>{drop.skipped ? `${drop.skipped} junk skipped` : "ready"}</span>
        <button type="button" className="btn ghost sm" onClick={() => ui.set({ activeDrop: null })}><Icon name="plus" size={13} /> New drop</button>
      </div>
      {drop.status !== "organized" && (
        <>
          <h1 className="drop-title">What are <b>these files</b>?</h1>
          <div className="label-card">
            <textarea ref={box} className="label-input" rows={3} value={text} disabled={busy}
              placeholder="e.g. Final architecture docs, datasets, and meeting notes with Rahul for the Pune Solar project"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) organize(); }} />
            <div className="row" style={{ justifyContent: "space-between" }}>
              <button type="button" className={`talk ${recording ? "recording" : ""}`} disabled={!canSpeak || busy || a.voiceText.isPending}
                onPointerDown={startTalk} onPointerUp={stopTalk} onPointerLeave={stopTalk}
                title={canSpeak ? "Hold (or hold Ctrl+Space) and speak — English, Hindi or Hinglish" : "Set up voice in Settings → Voice"}>
                {a.voiceText.isPending ? <Icon name="loader" spin /> : <Icon name="mic" />}
                {recording ? "Listening… release to stop" : a.voiceText.isPending ? "Transcribing…" : "Hold to speak"}
              </button>
              <button type="button" className="btn primary" disabled={!text.trim() || busy || a.label.isPending} onClick={organize}>
                {busy ? <Icon name="loader" spin /> : <Icon name="sparkles" />} {busy ? (drop.status === "importing" ? "Adding files…" : "Organizing…") : "Organize with AI"}
              </button>
            </div>
            {!canSpeak && <p className="tiny muted" style={{ margin: 0 }}>Voice is off — set it up in Settings → Voice, or type.</p>}
            {drop.status === "failed" && <p className="small" style={{ color: "var(--bad)", margin: 0 }}>{drop.error}</p>}
          </div>
          <FileList drop={drop} />
        </>
      )}
      {drop.status === "organized" && <Result drop={drop} />}
    </section>
  );
}

function Result({ drop }: { drop: Drop }) {
  const plan = drop.plan as { project_name?: string; summary?: string; tags?: string[]; entities?: { name: string; type: string }[] } | null;
  const folders = groupByFolder(drop);
  return (
    <div className="result-card">
      <div className="tiny muted row" style={{ gap: 6 }}><Icon name="sparkles" size={12} /> Organized by {drop.engine === "rules" ? "Folio's offline rules" : drop.engine}</div>
      <h2 className="result-title">{plan?.project_name ?? drop.project?.name}</h2>
      {drop.label && <blockquote className="result-label">“{drop.label}”</blockquote>}
      {plan?.summary && <p className="result-summary">{plan.summary}</p>}
      <div className="file-tags" style={{ marginBottom: 6 }}>
        {(plan?.entities ?? []).filter((e) => e.type !== "Date").map((e) => <span key={e.name} className="tag-chip sm">{e.type === "Person" ? "👤 " : ""}{e.name}</span>)}
        {(plan?.tags ?? []).map((t) => <span key={t} className="tag-chip sm">{t}</span>)}
      </div>
      <div className="result-folders">
        {folders.map(([folder, files]) => (
          <div key={folder} className="result-folder">
            <div className="row" style={{ gap: 6 }}><Icon name="folder" size={14} /><b>{folder}</b><span className="tiny muted">{files.length}</span></div>
            {files.map((f) => <div key={f.source_id} className="tiny muted ellipsis" title={f.rel_path}><Icon name={kindIcon(f.kind)} size={11} /> {f.name}</div>)}
          </div>
        ))}
      </div>
      <div className="row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
        <button type="button" className="btn" onClick={() => ui.set({ activeDrop: drop.id })}><Icon name="pencil" /> Re-label</button>
        {drop.project && <button type="button" className="btn" onClick={() => { selectEntity(drop.project!.id); ui.set({ view: "graph" }); }}><Icon name="graph" /> View in graph</button>}
        <button type="button" className="btn primary" onClick={() => openProject(drop.id)}><Icon name="layers" /> Open project</button>
      </div>
    </div>
  );
}

function FileList({ drop }: { drop: Drop }) {
  const files = drop.files ?? [];
  if (!files.length) return drop.status === "importing" ? <p className="small muted">Adding files…</p> : null;
  return (
    <div className="drop-files">
      {files.slice(0, 40).map((f) => (
        <div key={f.source_id} className="row small ellipsis" title={f.rel_path}><Icon name={kindIcon(f.kind)} size={12} className="muted" /> <span className="ellipsis">{f.rel_path}</span></div>
      ))}
      {files.length > 40 && <div className="tiny muted">… and {files.length - 40} more</div>}
    </div>
  );
}

function RecentDrops() {
  const { data: drops } = useDrops();
  if (!drops?.length) return null;
  return (
    <section className="recent-drops">
      <div className="sidebar-head" style={{ padding: "0 0 8px" }}><h2>Recent drops</h2></div>
      <div className="recent-grid">
        {drops.slice(0, 9).map((d) => (
          <button type="button" key={d.id} className="recent-card"
            onClick={() => (d.status === "organized" ? openProject(d.id) : ui.set({ activeDrop: d.id }))}>
            <b className="ellipsis">{d.project?.name ?? (d.label ? "Organizing…" : "Waiting for a label")}</b>
            <span className="tiny muted ellipsis">{d.label ?? d.paths.map(basename).join(", ")}</span>
            <span className="row tiny" style={{ gap: 6 }}>
              <span className={`badge ${d.status === "organized" ? "ok" : d.status === "failed" ? "bad" : "warn"}`}>{d.status}</span>
              <span className="muted">{d.file_count} files · {shortDate(d.created_at)}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
