/** Top bar: search, background-work indicator, privacy (always visible), undo/redo, settings. */
import { useJobs, useKnowledgeActions, useStatus } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { Logo } from "@/components/Logo";
import { openAdd, openSettings, ui } from "@/state/selection";

function WorkIndicator() {
  const { data: jobs } = useJobs();
  const running = jobs?.filter((j) => j.status === "running") ?? [];
  const queued = jobs?.filter((j) => j.status === "queued").length ?? 0;
  if (!running.length && !queued) return null;
  const top = running[0];
  return (
    <button type="button" className="btn ghost sm job-status" onClick={() => ui.set({ leftTab: "activity" })} title="Background work">
      <Icon name="loader" spin />
      <span className="small ellipsis">
        {top ? `${top.kind === "scan_root" ? "Scanning" : top.kind === "extract_source" ? "Extracting" : top.kind === "download_speech_model" ? "Downloading" : "Indexing"}${top.message ? ` · ${top.message}` : ""}` : "Queued"}
        {queued ? ` (+${queued})` : ""}
      </span>
    </button>
  );
}

export function TopBar() {
  const { data: status } = useStatus();
  const { undo, redo } = useKnowledgeActions();
  const cloud = status?.network_mode === "cloud" || status?.cloud_enabled;

  return (
    <header className="topbar">
      <div className="brand">
        <Logo size={28} />
        Folio
      </div>
      <button type="button" className="searchbox" onClick={() => ui.set({ modal: "search" })}>
        <Icon name="search" />
        <span className="label">Search files, topics, people, text…</span>
        <span className="kbd">/</span>
      </button>
      <button type="button" className="btn primary sm topbar-add" onClick={() => openAdd()} title="Add files or folders (or drop them on the window)">
        <Icon name="plus" size={14} /> Add
      </button>
      <span className="spacer" />
      <WorkIndicator />
      <button
        type="button"
        className={`badge ${cloud ? "warn" : "ok"}`}
        style={{ border: 0, cursor: "pointer", height: 24, padding: "0 10px" }}
        onClick={() => openSettings("privacy")}
        title={cloud ? `Cloud AI: file text may be sent to ${status?.llm.label ?? "the AI provider"}; working data stays local` : "AI processing stays on this device; optional Drive backups require your explicit action"}
      >
        <Icon name={cloud ? "cloud" : "shield"} size={13} />
        {cloud ? `Cloud AI · ${status?.llm.label ?? "on"}` : "Local AI"}
      </button>
      <div className="row" style={{ gap: 2 }}>
        <button type="button" className="btn ghost icon-only" title="Undo (Ctrl+Z)" onClick={() => undo.mutate(undefined)}><Icon name="undo" /></button>
        <button type="button" className="btn ghost icon-only" title="Redo (Ctrl+Shift+Z)" onClick={() => redo.mutate(undefined)}><Icon name="redo" /></button>
        <button type="button" className="btn ghost icon-only" title="Settings" onClick={() => openSettings()}><Icon name="settings" /></button>
      </div>
    </header>
  );
}
