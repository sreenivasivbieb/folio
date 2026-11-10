/** Projects: what the AI organized from each labelled drop. */
import type { DiskPreview, Drop } from "@folio/api-client";
import { useMemo, useState } from "react";
import { useDropActions, useDrops } from "@/api/queries";
import { EmptyState } from "@/components/EmptyState";
import { Icon, kindIcon } from "@/components/Icon";
import { Modal } from "@/components/Modal";
import { basename, shortDate } from "@/lib/format";
import { openAdd, selectEntity, selectSource, ui } from "@/state/selection";
import { groupByFolder, latestProjects } from "@/lib/drops";

type Plan = { project_name?: string; summary?: string; tags?: string[]; entities?: { name: string; type: string }[] };

export function ProjectsView() {
  const { data: drops, isPending } = useDrops();
  const chosen = ui.use((s) => s.projectDrop);
  // One card per project: the latest organized drop for it.
  const projects = useMemo(() => latestProjects(drops ?? []), [drops]);
  const active = projects.find((d) => d.id === chosen) ?? projects[0];

  if (!isPending && !projects.length) {
    return (
      <div className="view" style={{ display: "grid", placeItems: "center" }}>
        <EmptyState icon="layers" tag={["Projects", "Organized from your labels"]} title={<>No <b>projects</b> yet</>}
          actions={<button type="button" className="btn primary" onClick={() => openAdd()}><Icon name="plus" /> Drop files</button>}>
          Drop files or a project folder, say or type what they are, and the AI organizes them into a project here.
        </EmptyState>
      </div>
    );
  }
  return (
    <div className="view projects-view">
      <aside className="project-list">
        {projects.map((d) => {
          const plan = d.plan as Plan | null;
          return (
            <button type="button" key={d.id} className={`project-card ${active?.id === d.id ? "active" : ""}`}
              onClick={() => ui.set({ projectDrop: d.id })}>
              <b className="ellipsis">{d.project!.name}</b>
              <span className="small muted project-card-summary">{plan?.summary ?? d.label}</span>
              <span className="tiny muted">{d.file_count} files · {shortDate(d.created_at)}</span>
            </button>
          );
        })}
      </aside>
      {active && <ProjectDetail drop={active} />}
    </div>
  );
}

function ProjectDetail({ drop }: { drop: Drop }) {
  const plan = drop.plan as Plan | null;
  const [disk, setDisk] = useState(false);
  const people = (plan?.entities ?? []).filter((e) => e.type === "Person" || e.type === "Organization");
  const dates = (plan?.entities ?? []).filter((e) => e.type === "Date");
  return (
    <section className="project-detail scroll">
      <div className="tiny muted row" style={{ gap: 6 }}><Icon name="sparkles" size={12} />
        {drop.engine === "rules" ? "Organized by offline rules" : `Organized by ${drop.engine}`} · {drop.paths.map(basename).join(", ")}
      </div>
      <h2 className="result-title">{drop.project!.name}</h2>
      {drop.label && <blockquote className="result-label">“{drop.label}”</blockquote>}
      {plan?.summary && <p className="result-summary">{plan.summary}</p>}
      <div className="file-tags" style={{ margin: "4px 0 14px" }}>
        {people.map((e) => <span key={e.name} className="tag-chip sm">{e.type === "Person" ? "👤" : "🏢"} {e.name}</span>)}
        {(plan?.tags ?? []).map((t) => <span key={t} className="tag-chip sm">{t}</span>)}
        {dates.map((e) => <span key={e.name} className="tag-chip sm">📅 {e.name}</span>)}
      </div>
      <div className="row wrap" style={{ gap: 8, marginBottom: 16 }}>
        <button type="button" className="btn" onClick={() => { selectEntity(drop.project!.id); ui.set({ view: "graph" }); }}><Icon name="graph" /> Show in graph</button>
        <button type="button" className="btn" onClick={() => { selectEntity(drop.project!.id); ui.set({ view: "timeline" }); }}><Icon name="clock" /> Timeline</button>
        <button type="button" className="btn" onClick={() => ui.set({ view: "drop", activeDrop: drop.id })}><Icon name="pencil" /> Re-label</button>
        <button type="button" className="btn" onClick={() => setDisk(true)} disabled={drop.mode !== "copy"}
          title={drop.mode === "copy" ? "Move the original files into these folders" : "Files were moved into Folio — nothing to tidy on disk"}>
          <Icon name="folder" /> {drop.disk ? "Organized on disk · Undo…" : "Preview & organize on disk"}
        </button>
      </div>
      <div className="project-folders">
        {groupByFolder(drop).map(([folder, files]) => (
          <div key={folder} className="project-folder">
            <div className="row" style={{ gap: 6, marginBottom: 6 }}><Icon name="folder" size={15} /><b>{folder}</b><span className="tiny muted">{files.length}</span></div>
            {files.map((f) => (
              <button type="button" key={f.source_id} className="project-file" onClick={() => selectSource(f.source_id)} title={f.rel_path}>
                <Icon name={kindIcon(f.kind)} size={13} className="muted" /><span className="ellipsis">{f.name}</span>
                {f.status !== "indexed" && <span className={`badge ${f.status}`}>{f.status}</span>}
              </button>
            ))}
          </div>
        ))}
      </div>
      {disk && <DiskModal drop={drop} onClose={() => setDisk(false)} />}
    </section>
  );
}

function DiskModal({ drop, onClose }: { drop: Drop; onClose: () => void }) {
  const a = useDropActions();
  const [preview, setPreview] = useState<DiskPreview | null>(null);
  const applied = !!drop.disk;
  const load = () => a.diskPreview.mutate(drop.id, { onSuccess: (p) => p && setPreview(p) });
  return (
    <Modal title={<><Icon name="folder" /> Organize on disk</>} onClose={onClose}
      footer={<>
        <span className="small muted grow">{applied ? "These files were moved; undo puts every one back." : "Nothing moves until you press Organize."}</span>
        <button type="button" className="btn" onClick={onClose}>Close</button>
        {applied
          ? <button type="button" className="btn primary" disabled={a.diskUndo.isPending} onClick={() => a.diskUndo.mutate(drop.id, { onSuccess: onClose })}><Icon name="undo" /> Undo</button>
          : <button type="button" className="btn primary" disabled={!preview?.moves.length || a.diskApply.isPending}
              onClick={() => a.diskApply.mutate(drop.id, { onSuccess: onClose })}><Icon name="check" /> Organize {preview?.moves.length ?? ""} files</button>}
      </>}>
      {applied ? (
        <p className="small">Organized inside <span className="mono">{String((drop.disk as { root?: string }).root ?? "")}</span>.</p>
      ) : !preview ? (
        <div className="stack">
          <p className="small text-2" style={{ margin: 0 }}>Folio can move the original files into the folders above, inside the folder you dropped. Junk (node_modules, build output…) is never touched.</p>
          <button type="button" className="btn" style={{ alignSelf: "flex-start" }} disabled={a.diskPreview.isPending} onClick={load}>
            {a.diskPreview.isPending ? <Icon name="loader" spin /> : <Icon name="eye" />} Preview the moves
          </button>
        </div>
      ) : preview.moves.length === 0 ? (
        <p className="small">Everything is already in place.</p>
      ) : (
        <div className="disk-moves">
          <div className="tiny muted" style={{ marginBottom: 6 }}>Inside <span className="mono">{preview.root}</span></div>
          {preview.moves.map((m) => (
            <div key={m.from} className="disk-move small">
              <span className="ellipsis muted" title={m.from}>{m.from.replace(preview.root, "") || m.from}</span>
              <Icon name="chevronRight" size={12} />
              <span className="ellipsis" title={m.to}><b>{m.folder}</b>/{basename(m.to)}</span>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
