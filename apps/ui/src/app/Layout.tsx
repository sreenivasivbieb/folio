/**
 * Three panes + voice bar:
 *   left   — sources / review queue / jobs / history
 *   main   — the four views over one data model (graph, swimlane, timeline, table)
 *   right  — evidence viewer, file viewer, or the selected entity's card
 *   bottom — push-to-talk and typed labels
 */
import { useClaim, useReview } from "@/api/queries";
import { useCoreEvents } from "@/api/events";
import { EntityCardPanel } from "@/features/entities/EntityCardPanel";
import { EvidenceViewer, SourceViewer } from "@/features/evidence/EvidenceViewer";
import { ExportMenu } from "@/features/export/ExportMenu";
import { HistoryPanel } from "@/features/history/HistoryPanel";
import { JobsPanel } from "@/features/jobs/JobsPanel";
import { ReviewPanel } from "@/features/review/ReviewPanel";
import { SchemaEditor } from "@/features/schema/SchemaEditor";
import { SearchPalette } from "@/features/search/SearchPalette";
import { SourcesPanel } from "@/features/sources/SourcesPanel";
import { VoiceBar } from "@/features/voice/VoiceBar";
import { type LeftTab, ui, type ViewName } from "@/state/selection";
import { toasts } from "@/state/toast";
import { GraphView } from "@/views/graph/GraphView";
import { SwimlaneView } from "@/views/swimlane/SwimlaneView";
import { TableView } from "@/views/table/TableView";
import { TimelineView } from "@/views/timeline/TimelineView";
import { TopBar } from "./TopBar";
import { useShortcuts } from "./useShortcuts";

const VIEWS: { id: ViewName; label: string }[] = [
  { id: "graph", label: "Graph" },
  { id: "swimlane", label: "Swimlane" },
  { id: "timeline", label: "Timeline" },
  { id: "table", label: "Table" },
];

function LeftPanel() {
  const tab = ui.use((s) => s.leftTab);
  const { data: review } = useReview();
  const reviewCount = review ? review.total_proposed + review.merge_suggestions.length + review.flagged.length : 0;
  const tabs: { id: LeftTab; label: string; count?: number }[] = [
    { id: "sources", label: "Files" },
    { id: "review", label: "Review", count: reviewCount },
    { id: "jobs", label: "Jobs" },
    { id: "history", label: "History" },
  ];
  return (
    <aside className="left">
      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <button type="button" key={t.id} role="tab" className="tab" aria-selected={tab === t.id} onClick={() => ui.set({ leftTab: t.id })}>
            {t.label}
            {!!t.count && <span className="count">{t.count}</span>}
          </button>
        ))}
      </div>
      {tab === "sources" && <SourcesPanel />}
      {tab === "review" && <ReviewPanel />}
      {tab === "jobs" && <JobsPanel />}
      {tab === "history" && <HistoryPanel />}
    </aside>
  );
}

function MainArea() {
  const view = ui.use((s) => s.view);
  return (
    <main className="main">
      <div className="tabs" role="tablist" style={{ background: "var(--panel)" }}>
        {VIEWS.map((v, i) => (
          <button type="button" key={v.id} role="tab" className="tab" aria-selected={view === v.id} onClick={() => ui.set({ view: v.id })} title={`${v.label} (${i + 1})`}>
            {v.label}
          </button>
        ))}
      </div>
      {view === "graph" && <GraphView />}
      {view === "swimlane" && <SwimlaneView />}
      {view === "timeline" && <TimelineView />}
      {view === "table" && <TableView />}
    </main>
  );
}

function RightPanel() {
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
      <div className="empty" style={{ textAlign: "left", lineHeight: 1.6 }}>
        <p><b>How Folio works</b></p>
        <ol style={{ paddingLeft: 18 }}>
          <li>Add a folder — files are indexed locally and never moved.</li>
          <li>Select a file and say (or type) what it is: <i>“This PDF is the Acme contract, Priya owns it.”</i></li>
          <li>Review proposed facts; every fact links to its page or second.</li>
          <li>Explore as a graph, swimlane, timeline or table. Ctrl+Z undoes anything.</li>
        </ol>
      </div>
    );
  return <aside className="right">{content}</aside>;
}

function Toasts() {
  const items = toasts.use((s) => s.items);
  return (
    <div className="toasts" aria-live="polite">
      {items.map((t) => <div key={t.id} className={`toast ${t.tone}`}>{t.text}</div>)}
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
      <LeftPanel />
      <MainArea />
      <RightPanel />
      <VoiceBar />
      <Toasts />
      {modal === "search" && <SearchPalette />}
      {modal === "schema" && <SchemaEditor />}
      {modal === "export" && <ExportMenu />}
    </div>
  );
}
