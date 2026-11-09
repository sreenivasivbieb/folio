/** Put a stored file back on the computer: moved out of Folio, or a copy. */
import { useState } from "react";
import { useSource, useVaultActions } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { Modal } from "@/components/Modal";
import { basename } from "@/lib/format";
import { ui } from "@/state/selection";
import { toast } from "@/state/toast";
import { type Mode, ModeChoice } from "./ModeChoice";
import { pickFolder } from "./pick";

export function ExportModal() {
  const id = ui.use((s) => s.exportId);
  const { data } = useSource(id);
  const src = data?.source;
  const [mode, setMode] = useState<Mode | null>(null);
  const [dest, setDest] = useState<string | null>(null);
  const { exportFile } = useVaultActions();
  const close = () => ui.set({ modal: "none", exportId: null });
  const origin = src?.origin_path ?? null;
  const run = () => {
    if (!id || !mode) return;
    exportFile.mutate({ id, mode, dest_dir: dest }, {
      onSuccess: (r) => {
        toast(`${mode === "move" ? "Moved" : "Copied"} to ${r?.detail ?? "folder"}`);
        if (mode === "move") ui.set({ selection: { kind: "none" }, openSourceId: null });
        close();
      },
    });
  };
  return (
    <Modal
      title={<><Icon name="external" /> Export {src ? basename(src.path) : "file"}</>}
      onClose={close}
      footer={<>
        <button type="button" className="btn" onClick={close}>Cancel</button>
        <button type="button" className="btn primary" disabled={!mode || (!dest && !origin) || exportFile.isPending} onClick={run}>
          {exportFile.isPending ? <Icon name="loader" spin /> : <Icon name="check" />} Export
        </button>
      </>}
    >
      <div className="stack" style={{ gap: 14 }}>
        <div>
          <div className="field-label">Destination</div>
          <div className="row">
            <span className="input grow ellipsis" style={{ display: "flex", alignItems: "center" }} title={dest ?? origin ?? ""}>
              {dest ?? (origin ? `Original folder · ${origin.replace(/[\\/][^\\/]*$/, "")}` : "Choose a folder")}
            </span>
            <button type="button" className="btn" onClick={async () => setDest(await pickFolder())}><Icon name="folder" /> Choose…</button>
          </div>
        </div>
        <div>
          <div className="field-label">Keep it in Folio?</div>
          <ModeChoice value={mode} onChange={setMode}
            move="Move it out: it leaves Folio (with its passages and unverified facts) and lives only in that folder."
            copy="Export a copy: it stays in Folio as well." />
        </div>
      </div>
    </Modal>
  );
}
