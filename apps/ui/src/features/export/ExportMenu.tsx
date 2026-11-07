/** Export (FR-9): JSON and GraphML are lossless round trips; Markdown and CSV are for people. */
import { useApi } from "@/api/client";
import { inTauri } from "@/api/connection";
import { Modal } from "@/components/Modal";
import { toast } from "@/state/toast";
import { ui } from "@/state/selection";

const FORMATS = [
  { id: "json", file: "folio-export.json", text: "JSON — everything, including full history (re-importable)" },
  { id: "graphml", file: "folio-graph.graphml", text: "GraphML — the graph with provenance (Gephi, yEd; re-importable)" },
  { id: "markdown", file: "folio-export.md", text: "Markdown — readable notes, one section per entity" },
  { id: "csv", file: "folio-export-csv.zip", text: "CSV — entities, aliases, claims, evidence" },
] as const;

export function ExportMenu() {
  const { conn } = useApi();
  const close = () => ui.set({ modal: "none" });

  const run = async (fmt: (typeof FORMATS)[number]) => {
    try {
      const res = await fetch(`${conn.baseUrl}/api/export/${fmt.id}`, { headers: { Authorization: `Bearer ${conn.token}` } });
      if (!res.ok) throw new Error(`export failed (${res.status})`);
      const bytes = new Uint8Array(await res.arrayBuffer());
      if (inTauri) {
        const { save } = await import("@tauri-apps/plugin-dialog");
        const { invoke } = await import("@tauri-apps/api/core");
        const path = await save({ defaultPath: fmt.file });
        if (!path) return;
        await invoke("save_file", { path, contents: Array.from(bytes) });
      } else {
        const url = URL.createObjectURL(new Blob([bytes]));
        const a = Object.assign(document.createElement("a"), { href: url, download: fmt.file });
        a.click();
        URL.revokeObjectURL(url);
      }
      toast(`Exported ${fmt.file}`);
      close();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <Modal title="Export" onClose={close}>
      {FORMATS.map((f) => (
        <div key={f.id} className="palette-item" onClick={() => void run(f)}>
          <b style={{ width: 80 }}>{f.id}</b> <span className="muted">{f.text}</span>
        </div>
      ))}
    </Modal>
  );
}
