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
import { EmptyState } from "@/components/EmptyState";
import { Icon } from "@/components/Icon";
import { selectClaims, selectEntity, ui } from "@/state/selection";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function rgb(color: string): [number, number, number] {
  const m = color.match(/^#?([0-9a-f]{6})$/i);
  if (!m) return [136, 136, 136];
  const n = Number.parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Solid tint of ``color`` towards the canvas: readable on white and on dark, unlike rgba alpha
 * (WebGL blending made "faded" nodes and edges almost invisible on the light theme). */
function tint(color: string, amount: number): string {
  const [r, g, b] = rgb(color);
  const [br, bg, bb] = rgb(cssVar("--surface"));
  const mix = (a: number, z: number) => Math.round(a + (z - a) * amount);
  return `rgb(${mix(r, br)}, ${mix(g, bg)}, ${mix(b, bb)})`;
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
      size: (node.type === "Document" ? 4 : 6) + Math.min(14, Math.sqrt(node.degree) * 3),
      // Confirmed: full colour. Proposed (awaiting review): a lighter tint of the same colour.
      color: node.status === "verified" ? typeColor(schema, node.type) : tint(typeColor(schema, node.type), 0.35),
      entityType: node.type,
      status: node.status,
    });
  });
  for (const e of data.edges) {
    if (!g.hasNode(e.source) || !g.hasNode(e.target)) continue;
    const proposed = e.status === "proposed";
    g.addDirectedEdgeWithKey(e.id, e.source, e.target, {
      label: predicateLabel(e.predicate),
      size: proposed ? 1.2 : 2.4,
      color: e.status === "rejected" ? tint(cssVar("--bad"), 0.4) : proposed ? tint(cssVar("--text-3"), 0.25) : cssVar("--text-2"),
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
  const hoveredRef = useRef<string | null>(null);
  const actions = useKnowledgeActions();

  const graph = useMemo(() => (data ? buildGraph(data, schema) : null), [data, schema]);

  useEffect(() => {
    if (!graph || !container.current) return;
    const renderer = new Sigma(graph, container.current, {
      // The view can be momentarily 0px tall (narrow tiled windows, layout changes). Without this
      // Sigma throws, and the error used to unmount the entire app (blank window).
      allowInvalidContainer: true,
      // Edge labels only while the graph is small enough to read them; hover shows the rest.
      renderEdgeLabels: graph.size <= 40,
      edgeLabelSize: 10,
      labelSize: 13,
      labelWeight: "500",
      labelDensity: 0.6,
      labelGridCellSize: 110,
      enableEdgeEvents: true,
      defaultEdgeType: "arrow",
      // Sigma draws hover/selected labels on a white box: those get dark text (labelColor
      // attribute below); all other labels use the theme's text colour.
      labelColor: { attribute: "labelColor", color: cssVar("--text") },
      edgeLabelColor: { color: cssVar("--text-3") },
      labelRenderedSizeThreshold: 7,
      stagePadding: 120, // room for labels at the edges, and nodes clear of the legend overlay
      nodeReducer: (node, attrs) => {
        if (selectedRef.current.has(node)) return { ...attrs, highlighted: true, zIndex: 1, labelColor: "#18181b" };
        if (hoveredRef.current === node) return { ...attrs, labelColor: "#18181b" };
        return attrs;
      },
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
    renderer.on("enterNode", ({ node }) => { hoveredRef.current = node; });
    renderer.on("leaveNode", () => { hoveredRef.current = null; });
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
        <div className="seg">
          <button type="button" aria-selected={!neighbourhood} onClick={() => setNeighbourhood(false)}>Everything</button>
          <button type="button" aria-selected={neighbourhood} disabled={!focus} onClick={() => setNeighbourhood(true)}>Around selection</button>
        </div>
        {neighbourhood && (
          <select className="input" value={depth} onChange={(e) => setDepth(Number(e.target.value))} aria-label="Depth">
            {[1, 2, 3].map((d) => <option key={d} value={d}>{d} hop{d > 1 ? "s" : ""}</option>)}
          </select>
        )}
        <label className="row small text-2"><input type="checkbox" checked={mentions} onChange={(e) => setMentions(e.target.checked)} /> Show files</label>
        <label className="row small text-2"><input type="checkbox" checked={rejected} onChange={(e) => setRejected(e.target.checked)} /> Show rejected</label>
        <span className="spacer" />
        {selectedEntities.length === 2 && <ConnectOrMerge a={selectedEntities[0]} b={selectedEntities[1]} graph={graph} />}
        <span className="small muted">{data ? `${data.nodes.length} entities · ${data.edges.length} links` : ""}</span>
      </div>
      <div className="view">
        <div ref={container} className="graph-canvas" />
        {isLoading && <div className="empty-inline"><Icon name="loader" spin /></div>}
        {data && data.nodes.length === 0 && (
          <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
            <EmptyState icon="graph" title={<>Your knowledge <b>graph</b></>}>
              People, topics and organisations appear here as bubbles once facts are extracted — connect an AI model in Settings, or select a file and describe it below.
            </EmptyState>
          </div>
        )}
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
        {!!data?.nodes.length && <div className="legend">
          {Array.from(new Set(data.nodes.map((n) => n.type))).sort().map((t) => (
            <span key={t} className="row"><span className="dot" style={{ background: typeColor(schema, t) }} />{t}</span>
          ))}
          <span className="muted">bold = confirmed · light = awaiting review</span>
        </div>}
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
      <label className="small muted">Change relation</label>
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
        <button type="button" className="btn sm success" onClick={() => { actions.setClaimStatus.mutate({ ids: [claimId], status: "verified" }); onDone(); }}><Icon name="check" size={13} /> Confirm</button>
        <button type="button" className="btn sm danger" onClick={() => { actions.setClaimStatus.mutate({ ids: [claimId], status: "rejected" }); onDone(); }}><Icon name="x" size={13} /> Reject</button>
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
        <button type="button" className="btn sm" onClick={() => actions.merge.mutate({ keep: a, merge: b })}>
          Merge “{nb}” into “{na}”
        </button>
      )}
    </div>
  );
}
