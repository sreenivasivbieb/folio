import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { unwrap, useApi } from "@/api/client";
import { inTauri } from "@/api/connection";
import { useAction, useStatus } from "@/api/queries";
import { Icon } from "@/components/Icon";
import { toast } from "@/state/toast";

export function DriveTab() {
  const { client } = useApi();
  const { data: app } = useStatus();
  const { data: status } = useQuery({ queryKey: ["drive"], queryFn: async () => unwrap(await client.GET("/api/drive")), refetchInterval: 2000 });
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [url, setUrl] = useState("");
  useEffect(() => { if (status?.client_id) setClientId(status.client_id); if (status?.connected) setUrl(""); }, [status?.client_id, status?.connected]);
  const backups = useQuery({ queryKey: ["driveBackups"], enabled: !!status?.connected,
    queryFn: async () => unwrap(await client.GET("/api/drive/backups")) });
  const connect = useAction(async () => {
    const result = unwrap(await client.POST("/api/drive/connect", { body: { client_id: clientId, client_secret: secret || null } }));
    setUrl(result.authorization_url);
    setSecret("");
    return result;
  });
  const disconnect = useAction(async () => { setUrl(""); return unwrap(await client.DELETE("/api/drive")); }, "Local Drive credentials removed");
  const backup = useAction(async () => unwrap(await client.POST("/api/drive/backups")), "Backup saved to your Google Drive");
  const restore = useAction(async (fileId: string) => {
    if (!window.confirm("Restore this backup into the empty local project? Its local file paths will be rescanned where they exist.")) return null;
    return unwrap(await client.POST("/api/drive/restore", { body: { file_id: fileId } }));
  }, "Backup restored locally");
  const canRestore = !!app && app.counts.entities === 0 && app.counts.claims === 0;
  const openAuthorization = async () => {
    try {
      if (inTauri) {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("open_google_auth", { url });
      } else window.open(url, "_blank", "noopener,noreferrer");
    } catch (error) { toast((error as Error).message, "error"); }
  };
  return <div className="stack" style={{ gap: 16 }}>
    <div><h2>Your Google Drive</h2><p className="lead small text-2">Optional backup and restore. Folio keeps your working files, knowledge and credentials on this device. No Folio-owned storage or account is used.</p></div>
    <div className="callout"><Icon name="shield" /><div>A backup contains extracted knowledge, source paths and review history. It does not upload originals or API keys. Nothing uploads automatically.</div></div>
    {!status?.connected ? <>
      <p className="small text-2">Use your own Google Cloud project with the Drive API enabled and an OAuth client of type Desktop app. Import its credentials JSON, then sign in to your Google account. Use the same OAuth app on other devices to see its backups.</p>
      <label className="field">Import your Desktop OAuth credentials JSON
        <input type="file" accept="application/json,.json" onChange={async (event) => {
          const file = event.target.files?.[0]; if (!file) return;
          try {
            const data = JSON.parse(await file.text());
            if (!data.installed?.client_id || !data.installed?.client_secret) throw new Error("Choose a Google Desktop app credentials JSON file.");
            setClientId(data.installed.client_id); setSecret(data.installed.client_secret);
          } catch { toast("Could not read Desktop OAuth credentials JSON.", "error"); }
        }} />
      </label>
      <label className="field">OAuth client ID<input className="input" value={clientId} onChange={(e) => setClientId(e.target.value)} autoComplete="off" /></label>
      <label className="field">OAuth client secret<input type="password" className="input" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" placeholder={status?.secret_configured ? "Stored locally — leave blank to keep" : "Your own client secret"} /></label>
      <div className="row"><button type="button" className="btn primary" disabled={connect.isPending || !clientId || (!secret && !status?.secret_configured)} onClick={() => connect.mutate(undefined)}>Prepare Google sign-in</button>
        {url && <button type="button" className="btn" onClick={() => void openAuthorization()}>Continue in system browser</button>}</div>
    </> : <>
      <div className="row"><span className="badge verified">Connected with your credentials</span><span className="spacer" />
        <button type="button" className="btn sm" onClick={() => disconnect.mutate(undefined)}>Disconnect locally</button></div>
      <div className="row"><button type="button" className="btn primary" disabled={backup.isPending} onClick={() => backup.mutate(undefined)}><Icon name={backup.isPending ? "loader" : "cloud"} spin={backup.isPending} />{backup.isPending ? "Uploading backup…" : "Back up now"}</button>
        <button type="button" className="btn" onClick={() => void backups.refetch()}>Refresh backups</button></div>
      {backups.isPending && <p role="status">Loading your Folio backups…</p>}
      {backups.error && <p role="alert">{backups.error.message}</p>}
      {backups.data?.files.map((file) => <div className="file-chip" key={file.id}><Icon name="file" /><div className="grow"><b>{file.name}</b><div className="small text-2">{file.modifiedTime ? new Date(file.modifiedTime).toLocaleString() : ""}</div></div>
        <button type="button" className="btn sm" disabled={!canRestore || restore.isPending} onClick={() => restore.mutate(file.id)}>Restore locally</button></div>)}
      {backups.data?.files.length === 0 && <p className="small text-2">No Folio backups in this Drive account yet.</p>}
      {!canRestore && <p className="small text-2">Restore is available for an empty local project. Export your current knowledge before switching projects.</p>}
      <p className="small text-2">Disconnect removes credentials from this device. You can also revoke this OAuth app in your Google account permissions.</p>
    </>}
  </div>;
}
