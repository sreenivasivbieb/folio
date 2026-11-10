/** "Add to Folio": dump files or folders into Folio's own storage. */
import { useState } from "react";
import { useDropPreview, useVaultActions } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { Modal } from "@/components/Modal";
import { basename } from "@/lib/format";
import { ui } from "@/state/selection";
import { type Mode, ModeChoice } from "./ModeChoice";
import { pickPaths } from "./pick";

export function AddModal() {
  const paths = ui.use((s) => s.pendingPaths);
  const [mode, setMode] = useState<Mode | null>(null);
  const { add } = useVaultActions();
  const { data: counts, isFetching: counting, error: countError } = useDropPreview(paths);
  const close = () => ui.set({ modal: "none", pendingPaths: [] });
  const more = async (directory: boolean) => {
    const picked = await pickPaths(directory);
    if (picked.length) ui.set({ pendingPaths: Array.from(new Set([...ui.get().pendingPaths, ...picked])) });
  };
  const submit = () => {
    if (!mode || !paths.length) return;
    add.mutate({ paths, mode }, { onSuccess: () => { ui.set({ modal: "none", pendingPaths: [], leftTab: "activity" }); } });
  };

  return (
    <Modal
      title={<><Icon name="plus" /> Add to Folio</>}
      onClose={close}
      footer={<>
        <span className="small muted grow">
          {!paths.length ? "Nothing selected yet"
            : counting ? "Counting files…"
            : countError ? <span style={{ color: "var(--bad)" }}>{(countError as Error).message}</span>
            : counts ? <><b>{counts.files}</b> file{counts.files === 1 ? "" : "s"} to add{counts.skipped ? ` · ${counts.skipped} junk file${counts.skipped === 1 ? "" : "s"} skipped` : ""}</>
            : `${paths.length} item(s) selected`}
        </span>
        <button type="button" className="btn" onClick={close}>Cancel</button>
        <button type="button" className="btn primary" disabled={!mode || !paths.length || add.isPending || counts?.files === 0} onClick={submit}>
          {add.isPending ? <Icon name="loader" spin /> : <Icon name="check" />} {mode === "copy" ? "Copy into Folio" : mode === "move" ? "Move into Folio" : "Add"}
        </button>
      </>}
    >
      <div className="stack" style={{ gap: 14 }}>
        <div className="dropzone">
          <Icon name="download" size={22} />
          <b>Drop files or folders anywhere on the window</b>
          <span className="small muted">or</span>
          <div className="row">
            <button type="button" className="btn" onClick={() => void more(false)}><Icon name="file" /> Choose files</button>
            <button type="button" className="btn" onClick={() => void more(true)}><Icon name="folder" /> Choose a folder</button>
          </div>
        </div>
        {!!paths.length && (
          <div className="picked">
            {paths.map((p) => (
              <div key={p} className="row picked-row" title={p}>
                <Icon name="file" size={14} className="muted" />
                <span className="ellipsis grow">{basename(p)}</span>
                <span className="tiny muted ellipsis" style={{ maxWidth: "45%" }}>{p}</span>
                <button type="button" className="btn ghost sm icon-only" aria-label="Remove"
                  onClick={() => ui.set({ pendingPaths: paths.filter((x) => x !== p) })}><Icon name="x" size={13} /></button>
              </div>
            ))}
          </div>
        )}
        <div>
          <div className="field-label">Keep the original where it is?</div>
          <ModeChoice value={mode} onChange={setMode}
            move="It leaves its folder and lives only in Folio — no extra disk space. You can export it back anytime."
            copy="The original stays where it is; Folio keeps its own copy (uses space twice)." />
        </div>
        <p className="tiny muted" style={{ margin: 0 }}>Junk is skipped automatically: hidden files, node_modules, .git, build/dist output, virtual environments, lockfiles, binaries and disk images. Files already in Folio are left where they are.</p>
      </div>
    </Modal>
  );
}
