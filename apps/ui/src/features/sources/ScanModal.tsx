import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { unwrap, useApi } from "@/api/client";
import { useAction } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { Modal } from "@/components/Modal";
import { ui } from "@/state/selection";

export function ScanModal() {
  const { client } = useApi();
  const { data, isPending, error } = useQuery({ queryKey: ["scanLocations"],
    queryFn: async () => unwrap(await client.GET("/api/scan/locations")) });
  const [paths, setPaths] = useState<string[]>([]);
  const [hidden, setHidden] = useState(false);
  const [watch, setWatch] = useState(false);
  const [exclude, setExclude] = useState("");
  const [custom, setCustom] = useState("");
  useEffect(() => {
    if (!data) return;
    setPaths(data.locations.filter((l) => l.kind === "home").map((l) => l.path));
    setExclude(data.default_exclusions.join("\n"));
  }, [data]);
  const scan = useAction(async () => {
    const selected = [...new Set([...paths, ...custom.split("\n").map((s) => s.trim()).filter(Boolean)])];
    for (const path of selected) {
      unwrap(await client.POST("/api/roots", { body: { path, watch: watch && !/^(\/|[A-Za-z]:\\?)$/.test(path), include_hidden: hidden,
        exclude: exclude.split("\n").map((s) => s.trim()).filter(Boolean) } }));
    }
    ui.set({ modal: "none", leftTab: "activity" });
    return selected.length;
  }, "Scan queued — follow progress in Activity");
  return <Modal title={<><Icon name="search" /> Scan my computer</>} onClose={() => ui.set({ modal: "none" })} wide>
    <div className="stack" style={{ gap: 16 }}>
      <p>Choose any folder or mounted drive. Folio inventories readable files in place and extracts content from supported documents, images, audio and video.</p>
      <p className="small text-2">Other formats appear as metadata only. Files you cannot read, symbolic links, virtual system directories and Folio’s own data are skipped. Originals are never changed.</p>
      {isPending && <p role="status">Finding locations…</p>}
      {error && <p role="alert">Could not list locations: {error.message}</p>}
      {data?.locations.map((location) => <label key={location.path} className="file-chip" style={{ cursor: "pointer" }}>
        <input type="checkbox" checked={paths.includes(location.path)} onChange={(e) => setPaths((old) =>
          e.target.checked ? [...old, location.path] : old.filter((p) => p !== location.path))} />
        <span className="grow"><b>{location.label}</b><span className="small muted" style={{ display: "block", overflowWrap: "anywhere" }}>{location.path}</span></span>
      </label>)}
      <label className="field">Additional folders or drives (one absolute path per line)
        <textarea className="input" rows={2} value={custom} onChange={(e) => setCustom(e.target.value)} placeholder={navigator.userAgent.includes("Windows") ? "D:\\Documents" : "/mnt/my-drive"} />
      </label>
      <label className="row"><input type="checkbox" checked={hidden} onChange={(e) => setHidden(e.target.checked)} /> Include hidden files and folders</label>
      <label className="row"><input type="checkbox" checked={watch} onChange={(e) => setWatch(e.target.checked)} /> Watch selected folders for changes (except the entire filesystem)</label>
      <p className="small text-2">Large scans run once and rescan on later launches. Watching is optional because large folder trees can exceed Linux file watcher limits.</p>
      <label className="field">Excluded folder names or path patterns (one per line)
        <textarea className="input mono" rows={5} value={exclude} onChange={(e) => setExclude(e.target.value)} />
      </label>
      <details className="small text-2"><summary>Formats with content indexing</summary><p>{data?.supported_extensions.join(", ")}</p></details>
      <div className="row"><span className="spacer" /><button type="button" className="btn primary"
        disabled={scan.isPending || (!paths.length && !custom.trim())} onClick={() => scan.mutate(undefined)}>
        <Icon name={scan.isPending ? "loader" : "search"} spin={scan.isPending} /> {scan.isPending ? "Queuing scan…" : "Start scan"}
      </button></div>
    </div>
  </Modal>;
}
