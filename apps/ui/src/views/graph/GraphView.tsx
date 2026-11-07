/**
 * Relationship graph: entities as bubbles, relation claims as edges, coloured by entity type.
 * WebGL (Sigma.js) keeps ~10k nodes interactive. Edits: click an edge to re-type/verify/reject it,
 * select two bubbles (Ctrl/Shift+click) to merge them or connect them, double-click to expand.
 */
import type { GraphView as GraphData } from "@folio/api-client";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { useEffect, useMemo, useRef, useState } from "react";
import Sigma from "sigma";
import { useGraph, useKnowledgeActions } from "@/api/queries";
import { predicateLabel } from "@/lib/format";
import { type SchemaDef, typeColor, useSchemaDef } from "@/lib/schema";
import { selectClaims, selectEntity, ui } from "@/state/selection";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function alpha(hex: string, a: number): string {
  const n = Number.parseInt(hex.replace("#", ""), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function buildGraph(data: GraphData, schema: SchemaDef | null): Graph {
  const g = new Graph({ multi: true, type: "directed" });
  const n = data.nodes.length || 1;
  data.nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / n;
    g.addNode(node.id, {
      label: node.name,
      x: Math.cos(angle) * 100 + Math.random(),
      y: Math.sin(angle) * 100 + Math.random(),
      size: 5 + Math.min(14, Math.sqrt(node.degree) * 3),
      color: node.status === "verified" ? typeColor(schema, node.type) : alpha(typeColor(schema, node.type), 0.55),
      entityType: node.type,
      status: node.status,
    });
  });
  for (const e of data.edges) {
    if (!g.hasNode(e.source) || !g.hasNode(e.target)) continue;
    const proposed = e.status === "proposed";
    g.addDirectedEdgeWithKey(e.id, e.source, e.target, {
      label: predicateLabel(e.predicate),
      size: proposed ? 1 : 2.2,
      color: e.status === "rejected" ? alpha("#c0392b", 0.5) : proposed ? alpha("#b26b00", 0.45) : cssVar("--muted"),
      type: "arrow",
      status: e.status,
    });
  }
  if (g.order > 1) {
    // Strong gravity keeps disconnected clusters near the centre instead of drifting apart.
    forceAtlas2.assign(g, {
      iterations: g.order < 800 ? 250 : 80,
      settings: { ...forceAtlas2.inferSettings(g), strongGravityMode: true, gravity: 0.5, barnesHutOptimize: g.order > 400 },
    });
  }
  return g;
}

export function GraphView() {
  const focus = ui.use((s) => s.focusEntity);
  const selection = ui.use((s) => s.selection);
  const [neighbourhood, setNeighbourhood] = useState(false);
  const [depth, setDepth] = useState(2);
  const [mentions, setMentions] = useState(false);
  const [rejected, setRejected] = useState(false);
  const { data, isLoading } = useGraph(neighbourhood ? focus : null, depth, mentions, rejected);
  const schema = useSchemaDef();
  const container = useRef<HTMLDivElement>(null);
  const sigma = useRef<Sigma | null>(null);
  const selectedRef = useRef<Set<string>>(new Set());
  const actions = useKnowledgeActions();

  const graph = useMemo(() => (data ? buildGraph(data, schema) : null), [data, schema]);

  useEffect(() => {
    if (!graph || !container.current) return;
    const renderer = new Sigma(graph, container.current, {
      renderEdgeLabels: true,
      enableEdgeEvents: true,
      defaultEdgeType: "arrow",
      labelColor: { color: cssVar("--text") },
      edgeLabelColor: { color: cssVar("--muted") },
      labelRenderedSizeThreshold: 6,
      stagePadding: 70, // keep nodes clear of the legend overlay
      nodeReducer: (node, attrs) =>
        selectedRef.current.has(node) ? { ...attrs, highlighted: true, zIndex: 1 } : attrs,
      edgeReducer: (edge, attrs) => (selectedRef.current.has(edge) ? { ...attrs, size: 4, color: cssVar("--accent") } : attrs),
    });
    renderer.on("clickNode", ({ node, event }) => {
      const orig = event.original as MouseEvent;
      selectEntity(node, orig.ctrlKey || orig.metaKey || orig.shiftKey);
    });
    renderer.on("doubleClickNode", ({ node, event }) => {
      event.preventSigmaDefault();
      ui.set({ focusEntity: node });
      setNeighbourhood(true);
    });
    renderer.on("clickEdge", ({ edge }) => selectClaims([edge]));
    renderer.on("clickStage", () => ui.set({ selection: { kind: "none" } }));
    sigma.current = renderer;
    return () => {
      renderer.kill();
      sigma.current = null;
    };
  }, [graph]);

  useEffect(() => {
    selectedRef.current = new Set(selection.kind === "entity" || selection.kind === "claim" ? selection.ids : []);
    sigma.current?.refresh();
  }, [selection]);

  const selectedEntities = selection.kind === "entity" ? selection.ids : [];
  const selectedEdge = selection.kind === "claim" && graph?.hasEdge(selection.ids[0]) ? selection.ids[0] : null;

  return (
    <div className="view" style={{ display: "flex", flexDirection: "column" }}>
      <div className="toolbar">
        <div className="row">
          <button type="button" className={`tab`} aria-selected={!neighbourhood} onClick={() => setNeighbourhood(false)}>Everything</button>
          <button type="button" className={`tab`} aria-selected={neighbourhood} disabled={!focus} onClick={() => setNeighbourhood(true)}>Around selection</button>
        </div>
        {neighbourhood && (
          <select className="input" value={depth} onChange={(e) => setDepth(Number(e.target.value))} aria-label="Depth">
            {[1, 2, 3].map((d) => <option key={d} value={d}>{d} hop{d > 1 ? "s" : ""}</option>)}
          </select>
        )}
        <label className="row small"><input type="checkbox" checked={mentions} onChange={(e) => setMentions(e.target.checked)} /> document mentions</label>
        <label className="row small"><input type="checkbox" checked={rejected} onChange={(e) => setRejected(e.target.checked)} /> rejected</label>
        <span className="spacer" />
        {selectedEntities.length === 2 && <ConnectOrMerge a={selectedEntities[0]} b={selectedEntities[1]} graph={graph} />}
        <span className="small muted">{data ? `${data.nodes.length} entities · ${data.edges.length} relations` : ""}</span>
      </div>
      <div className="view">
        <div ref={container} className="graph-canvas" />
        {isLoading && <div className="empty">Loading graph…</div>}
        {data && data.nodes.length === 0 && <div className="empty">No entities yet. Add a folder, then label files by voice or review proposals.</div>}
        {selectedEdge && graph && (
          <EdgePanel
            claimId={selectedEdge}
            label={String(graph.getEdgeAttribute(selectedEdge, "label"))}
            status={String(graph.getEdgeAttribute(selectedEdge, "status"))}
            sourceType={String(graph.getNodeAttribute(graph.source(selectedEdge), "entityType"))}
            targetType={String(graph.getNodeAttribute(graph.target(selectedEdge), "entityType"))}
            onDone={() => ui.set({ selection: { kind: "none" } })}
            actions={actions}
            schema={schema}
          />
        )}
        <div className="legend">
          {Object.entries(schema?.entity_types ?? {}).map(([t, def]) => (
            <span key={t} className="row"><span className="dot" style={{ background: def.color }} />{t}</span>
          ))}
          <span className="muted">— solid = verified, faded = proposed</span>
        </div>
      </div>
    </div>
  );
}

function EdgePanel({ claimId, label, status, sourceType, targetType, onDone, actions, schema }: {
  claimId: string;
  label: string;
  status: string;
  sourceType: string;
  targetType: string;
  onDone: () => void;
  actions: ReturnType<typeof useKnowledgeActions>;
  schema: SchemaDef | null;
}) {
  const options = Object.entries(schema?.relation_types ?? {})
    .filter(([, r]) => (r.source.includes("*") || r.source.includes(sourceType)) && (r.target.includes("*") || r.target.includes(targetType)))
    .map(([n]) => n);
  return (
    <div className="floating stack">
      <strong>Relation: {label}</strong>
      <span className={`badge ${status}`} style={{ alignSelf: "flex-start" }}>{status}</span>
      <label className="small muted">Re-type</label>
      <select
        className="input"
        value=""
        onChange={(e) => {
          if (e.target.value) actions.editClaim.mutate({ id: claimId, changes: { predicate: e.target.value } });
          onDone();
        }}
      >
        <option value="">Choose…</option>
        {options.map((o) => <option key={o} value={o}>{predicateLabel(o)}</option>)}
      </select>
      <div className="row">
        <button type="button" className="btn small ok" onClick={() => { actions.setClaimStatus.mutate({ ids: [claimId], status: "verified" }); onDone(); }}>Verify</button>
        <button type="button" className="btn small bad" onClick={() => { actions.setClaimStatus.mutate({ ids: [claimId], status: "rejected" }); onDone(); }}>Delete (reject)</button>
      </div>
    </div>
  );
}

function ConnectOrMerge({ a, b, graph }: { a: string; b: string; graph: Graph | null }) {
  const schema = useSchemaDef();
  const actions = useKnowledgeActions();
  if (!graph?.hasNode(a) || !graph.hasNode(b)) return null;
  const ta = String(graph.getNodeAttribute(a, "entityType"));
  const tb = String(graph.getNodeAttribute(b, "entityType"));
  const na = String(graph.getNodeAttribute(a, "label"));
  const nb = String(graph.getNodeAttribute(b, "label"));
  const rels = Object.entries(schema?.relation_types ?? {}).filter(
    ([, r]) => (r.source.includes("*") || r.source.includes(ta)) && (r.target.includes("*") || r.target.includes(tb)),
  );
  return (
    <div className="row">
      <select
        className="input"
        value=""
        onChange={(e) => e.target.value && actions.createClaim.mutate({ subject_id: a, predicate: e.target.value, object_id: b })}
        title={`Connect ${na} → ${nb}`}
      >
        <option value="">Connect {na} →…</option>
        {rels.map(([n]) => <option key={n} value={n}>{predicateLabel(n)} {nb}</option>)}
      </select>
      {ta === tb && (
        <button type="button" className="btn small" onClick={() => actions.merge.mutate({ keep: a, merge: b })}>
          Merge “{nb}” into “{na}”
        </button>
      )}
    </div>
  );
}
