/**
 * App shell:
 *   sidebar   — Library / Review / Activity, plus AI-model and voice status
 *   main      — the four views over one data model (graph, swimlane, timeline, table)
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
import { useAddRoot } from "@/features/sources/SourcesPanel";
import { VoiceBar } from "@/features/voice/VoiceBar";
import { ScanModal } from "@/features/sources/ScanModal";
import { openSettings, ui, type ViewName } from "@/state/selection";
import { toasts } from "@/state/toast";
import { GraphView } from "@/views/graph/GraphView";
import { SwimlaneView } from "@/views/swimlane/SwimlaneView";
import { TableView } from "@/views/table/TableView";
import { TimelineView } from "@/views/timeline/TimelineView";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useShortcuts } from "./useShortcuts";

const VIEWS: { id: ViewName; label: string; icon: IconName }[] = [
  { id: "graph", label: "Graph", icon: "graph" },
  { id: "swimlane", label: "Swimlane", icon: "lanes" },
  { id: "timeline", label: "Timeline", icon: "clock" },
  { id: "table", label: "Table", icon: "table" },
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
  const addRoot = useAddRoot();
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
            {status.counts.entities} entities · {status.counts.claims} facts
            {status.counts.proposed ? <> · <button type="button" className="btn ghost sm" style={{ color: "var(--warn)" }} onClick={() => ui.set({ leftTab: "review" })}>{status.counts.proposed} to review</button></> : null}
          </span>
        )}
      </div>
      {empty ? (
        <div className="view" style={{ display: "grid", placeItems: "center" }}>
          <EmptyState
            icon="folder"
            title="Bring your files"
            actions={<>
              <button type="button" className="btn primary" onClick={() => ui.set({ modal: "scan" })}><Icon name="search" /> Scan my computer</button>
              <button type="button" className="btn primary" onClick={() => addRoot.mutate(true)}><Icon name="folder" /> Add a folder</button>
              <button type="button" className="btn" onClick={() => addRoot.mutate(false)}><Icon name="file" /> Add a file</button>
            </>}
          >
            PDFs, scans, images, Word and Markdown notes, audio, video and transcripts. Folio reads them in place — nothing is
            copied, moved or changed — and builds a knowledge graph you can check and correct.
          </EmptyState>
        </div>
      ) : (
        <>
          <Onboarding />
          {view === "graph" && <GraphView />}
          {view === "swimlane" && <SwimlaneView />}
          {view === "timeline" && <TimelineView />}
          {view === "table" && <TableView />}
        </>
      )}
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
      <EmptyState icon="info" title="Nothing selected">
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
  return (
    <div className="app">
      <TopBar />
      <Sidebar />
      <MainArea />
      <VoiceBar />
      <Inspector />
      <Toasts />
      {modal === "search" && <SearchPalette />}
      {modal === "settings" && <SettingsModal />}
      {modal === "scan" && <ScanModal />}
    </div>
  );
}
