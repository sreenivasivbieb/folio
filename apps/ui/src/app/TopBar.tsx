/** Top bar: search, privacy indicator (local vs cloud — always visible), undo/redo, tools. */
import { unwrap, useApi } from "@/api/client";
import { useAction, useKnowledgeActions, useStatus } from "@/api/queries";
import { ui } from "@/state/selection";

export function TopBar() {
  const { client } = useApi();
  const { data: status } = useStatus();
  const { undo, redo } = useKnowledgeActions();
  const setCloud = useAction(async (enabled: boolean) => unwrap(await client.PUT("/api/settings/cloud", { body: { enabled } })));
  const busy = (status?.jobs.queued ?? 0) + (status?.jobs.running ?? 0);
  const local = status?.network_mode !== "cloud";

  return (
    <div className="topbar">
      <span className="brand">Folio</span>
      <button type="button" className="btn" style={{ minWidth: 260, textAlign: "left", color: "var(--muted)" }} onClick={() => ui.set({ modal: "search" })}>
        Search entities & passages… <span className="kbd">Ctrl K</span>
      </button>
      <span className="spacer" />
      {busy > 0 && <span className="small muted" title="Background jobs">⟳ indexing {busy}</span>}
      {status && (
        <span className="small muted">{status.counts.entities} entities · {status.counts.claims} facts · {status.counts.proposed} to review</span>
      )}
      <button
        type="button"
        className={`badge ${local ? "local" : "cloud"}`}
        style={{ border: 0, cursor: "pointer" }}
        title={
          local
            ? "Everything runs on this machine. No network traffic. Click to allow cloud models for this project."
            : "Cloud models allowed for this project. Click to go back to local only."
        }
        onClick={() => {
          const next = !status?.cloud_enabled;
          if (!next || window.confirm("Allow cloud models for this project? Content may be sent to the configured provider.")) setCloud.mutate(next);
        }}
      >
        {status?.cloud_enabled ? "☁ cloud allowed" : "● local only"}
      </button>
      <button type="button" className="btn icon" title="Undo (Ctrl+Z)" onClick={() => undo.mutate(undefined)}>↶</button>
      <button type="button" className="btn icon" title="Redo (Ctrl+Shift+Z)" onClick={() => redo.mutate(undefined)}>↷</button>
      <button type="button" className="btn" onClick={() => ui.set({ modal: "schema" })}>Schema</button>
      <button type="button" className="btn" onClick={() => ui.set({ modal: "export" })}>Export</button>
    </div>
  );
}
