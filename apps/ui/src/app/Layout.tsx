/**
 * App shell:
 *   sidebar   — Library / Activity / Trash, plus AI-model and voice status
 *   main      — Drop & Label (intake), Projects (what the AI organized), Graph
 *   inspector — evidence viewer, file viewer, or the selected entity's card
 *   composer  — push-to-talk and typed labels
 */
import { useClaim, useJobs, useStatus } from "@/api/queries";
import { useCoreEvents } from "@/api/events";
import { EmptyState } from "@/components/EmptyState";
import { Icon, type IconName } from "@/components/Icon";
import { EntityCardPanel } from "@/features/entities/EntityCardPanel";
import { EvidenceViewer, SourceViewer } from "@/features/evidence/EvidenceViewer";
import { SearchPalette } from "@/features/search/SearchPalette";
import { SettingsModal } from "@/features/settings/SettingsModal";
import { VoiceBar } from "@/features/voice/VoiceBar";
import { ExportModal } from "@/features/vault/ExportModal";
import { useDropToAdd } from "@/features/vault/useDropToAdd";
import { openAdd, openSettings, type ViewName, ui } from "@/state/selection";
import { toasts } from "@/state/toast";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { GraphView } from "@/views/graph/GraphView";
import { DropView } from "@/views/drop/DropView";
import { ProjectsView } from "@/views/projects/ProjectsView";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useShortcuts } from "./useShortcuts";

const VIEWS: { id: ViewName; label: string; icon: IconName }[] = [
  { id: "drop", label: "Drop & Label", icon: "download" },
  { id: "projects", label: "Projects", icon: "layers" },
  { id: "graph", label: "Graph", icon: "graph" },
];

/** Tells the user what to do next instead of showing an empty canvas. */
function Onboarding() {
  const { data: status } = useStatus();
  const { data: jobs } = useJobs();
  if (!status) return null;
  const extracting = jobs?.some((j) => j.kind === "extract_source" && (j.status === "running" || j.status === "queued"));
  const { sources, entities, chunks } = status.counts;
  if (sources > 0 && !status.llm.configured && entities === 0) {
    return (
      <div className="banner">
        <div className="glyph"><Icon name="sparkles" /></div>
        <div className="grow">
          <b>Connect an AI model to extract people, topics and facts</b>
          <span className="small text-2">{sources} files are indexed ({chunks} passages) and searchable. Use your own key (OpenAI, OpenRouter, Qwen, Groq) or a local Ollama — or label files yourself below.</span>
        </div>
        <button type="button" className="btn primary" onClick={() => openSettings("ai")}>Connect a model</button>
      </div>
    );
  }
  if (extracting && entities === 0) {
    return (
      <div className="banner">
        <div className="glyph"><Icon name="loader" spin /></div>
        <div className="grow"><b>Extracting knowledge from your files…</b><span className="small text-2">Entities and facts appear here as each file is processed. Everything the AI proposes waits for your review.</span></div>
      </div>
    );
  }
  return null;
}

function MainArea() {
  const view = ui.use((s) => s.view);
  const { data: status } = useStatus();
  const empty = status && status.counts.sources === 0;
  return (
    <main className="main">
      <div className="viewbar">
        <div className="seg" role="tablist">
          {VIEWS.map((v, i) => (
            <button type="button" key={v.id} role="tab" aria-selected={view === v.id} onClick={() => ui.set({ view: v.id })} title={`${v.label} (${i + 1})`}>
              <Icon name={v.icon} size={14} /> {v.label}
            </button>
          ))}
        </div>
        <span className="spacer" />
        {status && (
          <span className="small muted">
            {status.counts.sources} files · {status.counts.entities} in the graph
          </span>
        )}
      </div>
      <ErrorBoundary resetKey={view}>
        {view === "drop" && <DropView />}
        {view === "projects" && <ProjectsView />}
        {view === "graph" && (empty
          ? (
            <div className="view" style={{ display: "grid", placeItems: "center" }}>
              <EmptyState icon="graph" tag={["Graph", "Built from your labels"]} title={<>Nothing to <b>connect</b> yet</>}
                actions={<button type="button" className="btn primary" onClick={() => openAdd()}><Icon name="plus" /> Drop files</button>}>
                Drop files and label them: projects, folders, people and topics appear here, linked.
              </EmptyState>
            </div>
          )
          : <><Onboarding /><GraphView /></>)}
      </ErrorBoundary>
    </main>
  );
}

function Inspector() {
  const evidence = ui.use((s) => s.evidence);
  const openSource = ui.use((s) => s.openSourceId);
  const selection = ui.use((s) => s.selection);
  const focus = ui.use((s) => s.focusEntity);
  const claimId = selection.kind === "claim" ? selection.ids[0] : null;
  const { data: claim } = useClaim(claimId);

  let content;
  if (evidence) content = <EvidenceViewer evidence={evidence} />;
  else if (openSource) content = <SourceViewer sourceId={openSource} />;
  else if (selection.kind === "entity") content = <EntityCardPanel entityId={selection.ids[selection.ids.length - 1]} />;
  else if (claim) content = <EntityCardPanel entityId={claim.subject_id} />;
  else if (focus) content = <EntityCardPanel entityId={focus} />;
  else
    content = (
      <EmptyState icon="info" title={<>Nothing <b>selected</b></>}>
        Click an entity in the graph, a file in the library, or search with <span className="kbd">Ctrl K</span>. Every fact shows where it came from —
        the page, the paragraph or the second in a video.
      </EmptyState>
    );
  return <aside className="inspector">{content}</aside>;
}

function Toasts() {
  const items = toasts.use((s) => s.items);
  return (
    <div className="toasts" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.tone}`}><Icon name={t.tone === "error" ? "alert" : "check"} size={14} />{t.text}</div>
      ))}
    </div>
  );
}

export function Layout() {
  useCoreEvents();
  useShortcuts();
  const modal = ui.use((s) => s.modal);
  const view = ui.use((s) => s.view);
  const dragging = useDropToAdd();
  return (
    <div className="app">
      <TopBar />
      <Sidebar />
      <MainArea />
      {view !== "drop" && <VoiceBar />}
      <Inspector />
      <Toasts />
      {modal === "search" && <SearchPalette />}
      {modal === "settings" && <SettingsModal />}
      {modal === "export" && <ExportModal />}
      {dragging && (
        <div className="drop-overlay"><div><Icon name="download" size={30} /><b>Drop to add to Folio</b><span>Then say or type what these files are</span></div></div>
      )}
    </div>
  );
}
