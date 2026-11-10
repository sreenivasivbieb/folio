/** Left sidebar: Library (files) · Activity (jobs + history) · Trash, plus the AI and voice
 * status cards — so it is always obvious whether extraction and voice are actually available. */
import { useFilePage, useJobs, useSources, useStatus, useVault } from "@/api/queries";
import { Icon, type IconName } from "@/components/Icon";
import { ActivityPanel } from "@/features/jobs/ActivityPanel";
import { SourcesPanel } from "@/features/sources/SourcesPanel";
import { TrashPanel } from "@/features/vault/TrashPanel";
import { type LeftTab, openSettings, ui } from "@/state/selection";

function NavItem({ id, icon, label, count, muted }: { id: LeftTab; icon: IconName; label: string; count?: number; muted?: boolean }) {
  const tab = ui.use((s) => s.leftTab);
  return (
    <button type="button" className="nav-item" aria-selected={tab === id} onClick={() => ui.set({ leftTab: id })}>
      <Icon name={icon} />
      {label}
      {!!count && <span className={`count ${muted ? "muted" : ""}`}>{count}</span>}
    </button>
  );
}

function StatusCards() {
  const { data: status } = useStatus();
  if (!status) return null;
  const llm = status.llm;
  const voice = status.voice;
  return (
    <div className="sidebar-foot">
      <button type="button" className="status-card" onClick={() => openSettings("ai")}>
        <span className={`status-dot ${llm.configured ? "ok" : "warn"}`} />
        <div className="grow">
          <div className="title">{llm.configured ? llm.label : "No AI model"}</div>
          <div className="sub ellipsis">{llm.configured ? llm.model : "Connect one to extract facts"}</div>
        </div>
        <Icon name="chevronRight" size={14} className="muted" />
      </button>
      <button type="button" className="status-card" onClick={() => openSettings("voice")}>
        <span className={`status-dot ${voice.speech_available && voice.microphone ? "ok" : voice.speech_downloadable ? "warn" : "off"}`} />
        <div className="grow">
          <div className="title">Voice {voice.speech_available ? "ready" : "not set up"}</div>
          <div className="sub ellipsis">
            {voice.speech_available
              ? (voice.microphone ? `Hold Ctrl+Space · ${voice.speech_engine === "cloud" ? "via your AI provider" : "offline"}` : "No microphone found")
              : voice.speech_downloadable ? "Connect Groq/OpenAI, or download the model" : "Type labels instead"}
          </div>
        </div>
        <Icon name="chevronRight" size={14} className="muted" />
      </button>
    </div>
  );
}

export function Sidebar() {
  const tab = ui.use((s) => s.leftTab);
  const { data: sources } = useSources();
  const { data: files } = useFilePage("", 0); // same count as the Files list (incl. metadata-only)
  const { data: jobs } = useJobs();
  const { data: vault } = useVault();
  const busy = jobs?.filter((j) => j.status === "running" || j.status === "queued").length ?? 0;
  const failed = jobs?.filter((j) => j.status === "failed").length ?? 0;
  return (
    <aside className="sidebar">
      <nav className="nav">
        <NavItem id="sources" icon="folder" label="Library" count={files?.total ?? sources?.length} muted />
        <NavItem id="activity" icon="activity" label="Activity" count={busy || failed} muted={!failed} />
        <NavItem id="trash" icon="trash" label="Trash" count={vault?.trashed} muted />
      </nav>
      <section className="sidebar-section">
        {tab === "sources" && <SourcesPanel />}
        {tab === "activity" && <ActivityPanel />}
        {tab === "trash" && <TrashPanel />}
      </section>
      <StatusCards />
    </aside>
  );
}
