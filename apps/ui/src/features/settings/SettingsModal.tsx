/** Settings: AI model (bring your own key), voice, privacy, type hints, data. */
import { useEffect, useMemo, useState } from "react";
import { unwrap, useApi } from "@/api/client";
import { useAction, useJobs, useLlmSettings, useSchema, useSettingsActions, useStatus } from "@/api/queries";
import { Icon, type IconName } from "@/components/Icon";
import { Modal } from "@/components/Modal";
import { EXPORT_FORMATS, exportFile } from "@/features/export/exportFile";
import { platform } from "@/lib/format";
import { type SettingsTab, ui } from "@/state/selection";
import { toast } from "@/state/toast";
import { DriveTab } from "./DriveTab";

const TABS: { id: SettingsTab; label: string; icon: IconName }[] = [
  { id: "ai", label: "AI model", icon: "sparkles" },
  { id: "voice", label: "Voice", icon: "mic" },
  { id: "privacy", label: "Privacy", icon: "shield" },
  { id: "hints", label: "Type hints", icon: "layers" },
  { id: "data", label: "Data", icon: "database" },
  { id: "drive", label: "Google Drive", icon: "cloud" },
];

export function SettingsModal() {
  const tab = ui.use((s) => s.settingsTab);
  return (
    <Modal title={<><Icon name="settings" /> Settings</>} onClose={() => ui.set({ modal: "none" })} wide bare>
      <div className="settings">
        <nav className="settings-nav">
          {TABS.map((t) => (
            <button key={t.id} type="button" className="nav-item" aria-selected={tab === t.id} onClick={() => ui.set({ settingsTab: t.id })}>
              <Icon name={t.icon} /> {t.label}
            </button>
          ))}
        </nav>
        <div className="settings-body">
          {tab === "ai" && <AiTab />}
          {tab === "voice" && <VoiceTab />}
          {tab === "privacy" && <PrivacyTab />}
          {tab === "hints" && <HintsTab />}
          {tab === "data" && <DataTab />}
          {tab === "drive" && <DriveTab />}
        </div>
      </div>
    </Modal>
  );
}

function AiTab() {
  const { data } = useLlmSettings();
  const actions = useSettingsActions();
  const status = data?.status;
  const presets = data?.presets ?? [];
  const [provider, setProvider] = useState("openrouter");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!data) return;
    const p = data.status.provider ?? "openrouter";
    setProvider(p);
    setBaseUrl(data.status.base_url ?? presets.find((x) => x.id === p)?.base_url ?? "");
    setModel(data.status.model ?? "");
  }, [data?.status.provider, data?.status.model]);

  const preset = presets.find((p) => p.id === provider);
  const sameProvider = status?.provider === provider;
  const hasStoredKey = sameProvider && !!status?.key_hint;
  const options = useMemo(() => Array.from(new Set([...(models.length ? models : []), ...(preset?.suggested_models ?? [])])), [models, preset]);
  const cloud = !/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])/.test(baseUrl);

  const choose = (id: string) => {
    setProvider(id);
    setBaseUrl(presets.find((p) => p.id === id)?.base_url ?? "");
    setModel("");
    setModels([]);
    setKey("");
  };

  return (
    <div className="stack" style={{ gap: 14 }}>
      <div>
        <h2>AI model</h2>
        <p className="lead small text-2" style={{ margin: 0 }}>
          Folio uses an LLM to find people, topics, organisations and facts in your files. Bring your own key from any
          OpenAI-compatible provider, or run one locally with Ollama. Without one, only simple patterns are extracted.
        </p>
      </div>

      {status?.configured ? (
        <div className="callout ok">
          <Icon name="check" />
          <div className="grow">
            <b>{status.label}</b> · <span className="mono">{status.model}</span>
            <div className="small text-2">{status.local ? "Runs on this computer" : "Hosted — file text is sent to this provider"}{status.key_hint ? ` · key ${status.key_hint}` : ""}</div>
          </div>
          <button type="button" className="btn sm" onClick={() => actions.testLlm.mutate(undefined, { onSuccess: (r) => toast(r.detail ?? "Connected") })}>
            {actions.testLlm.isPending ? <Icon name="loader" spin /> : <Icon name="activity" />} Test
          </button>
          <button type="button" className="btn sm ghost danger" onClick={() => actions.removeLlm.mutate(undefined)}>Remove</button>
        </div>
      ) : (
        <div className="callout warn"><Icon name="info" /><span>No AI model connected — Folio is using offline pattern matching, which finds very little in real documents.</span></div>
      )}

      <div className="provider-grid">
        {presets.map((p) => (
          <button key={p.id} type="button" className="provider" aria-selected={provider === p.id} onClick={() => choose(p.id)}>
            <b>{p.label}</b>
            <span>{p.id === "custom" ? "Any OpenAI-compatible URL" : p.needs_key ? "Your API key" : "Local, no key"}</span>
          </button>
        ))}
      </div>

      <div className="field">
        <label htmlFor="llm-url">Base URL</label>
        <input id="llm-url" className="input mono" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />
        <span className="hint">Any endpoint that speaks the OpenAI <span className="mono">/chat/completions</span> API — including a hackathon router.</span>
      </div>

      {(preset?.needs_key || provider === "custom") && (
        <div className="field">
          <label htmlFor="llm-key">API key</label>
          <div className="row">
            <input id="llm-key" className="input grow mono" type={showKey ? "text" : "password"} value={key} onChange={(e) => setKey(e.target.value)}
              placeholder={hasStoredKey ? `Saved (${status?.key_hint}) — leave empty to keep` : "sk-…"} autoComplete="off" />
            <button type="button" className="btn icon-only" onClick={() => setShowKey((v) => !v)} title={showKey ? "Hide" : "Show"}><Icon name="eye" /></button>
          </div>
          <span className="hint">
            Stored only on this computer (a private file in the app data folder) — never in the database or exports.
            {preset?.key_url && <> <a href={preset.key_url} target="_blank" rel="noreferrer">Get a key <Icon name="external" size={11} style={{ display: "inline" }} /></a></>}
          </span>
        </div>
      )}

      <div className="field">
        <label htmlFor="llm-model">Model</label>
        <div className="row">
          <input id="llm-model" className="input grow mono" list="llm-models" value={model} onChange={(e) => setModel(e.target.value)} placeholder="e.g. qwen/qwen-2.5-72b-instruct" />
          <datalist id="llm-models">{options.map((m) => <option key={m} value={m} />)}</datalist>
          <button type="button" className="btn" disabled={!baseUrl || actions.listModels.isPending}
            onClick={() => actions.listModels.mutate({ provider, base_url: baseUrl, api_key: key || null }, {
              onSuccess: (list) => { setModels(list); toast(`${list.length} models available`); },
            })}>
            {actions.listModels.isPending ? <Icon name="loader" spin /> : <Icon name="refresh" />} Load models
          </button>
        </div>
        {models.length > 0 && <span className="hint">{models.length} models loaded — start typing to filter.</span>}
      </div>

      {cloud && (
        <div className="callout"><Icon name="cloud" /><span>Saving a hosted provider turns on <b>cloud mode</b> for this project: the text of your files is sent to {preset?.label ?? "the provider"} for extraction. The top bar shows this at all times.</span></div>
      )}

      <div className="row">
        <span className="spacer" />
        {saved && <button type="button" className="btn" onClick={() => actions.extractAll.mutate(undefined)}><Icon name="sparkles" /> Extract all files now</button>}
        <button type="button" className="btn primary" disabled={!baseUrl || !model || actions.saveLlm.isPending}
          onClick={() => actions.saveLlm.mutate({ provider, base_url: baseUrl, model, api_key: key || null }, {
            onSuccess: () => { setSaved(true); setKey(""); },
          })}>
          {actions.saveLlm.isPending ? <Icon name="loader" spin /> : <Icon name="check" />} Save
        </button>
      </div>
    </div>
  );
}

function VoiceTab() {
  const { data: status } = useStatus();
  const { data: jobs } = useJobs();
  const actions = useSettingsActions();
  const voice = status?.voice;
  const os = platform();
  const download = jobs?.find((j) => j.kind === "download_speech_model" && (j.status === "running" || j.status === "queued"));
  const failed = jobs?.find((j) => j.kind === "download_speech_model" && j.status === "failed");
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div>
        <h2>Voice</h2>
        <p className="lead small text-2" style={{ margin: 0 }}>Speech is recognised on this computer with Whisper. Audio never leaves your machine.</p>
      </div>
      <div className={`callout ${voice?.speech_available ? "ok" : "warn"}`}>
        <Icon name={voice?.speech_available ? "check" : "download"} />
        <div className="grow">
          <b>Speech model {voice?.speech_available ? "ready" : "not downloaded"}</b>
          <div className="small text-2"><span className="mono">{voice?.speech_model}</span> · needed for voice labels and for indexing audio/video</div>
          {download && (
            <div style={{ marginTop: 8 }}>
              <div className="progress"><div style={{ width: `${Math.round(download.progress * 100)}%` }} /></div>
              <div className="tiny text-2" style={{ marginTop: 4 }}>{download.message ?? "starting…"}</div>
            </div>
          )}
          {failed && !download && <div className="small" style={{ color: "var(--bad)", marginTop: 4 }}>{failed.error?.split("\n")[0]}</div>}
        </div>
        {voice?.speech_downloadable && !download && (
          <button type="button" className="btn primary sm" onClick={() => actions.downloadSpeech.mutate(undefined)}>
            <Icon name="download" /> Download ({voice.speech_size_mb} MB)
          </button>
        )}
      </div>
      <div className={`callout ${voice?.microphone ? "ok" : "bad"}`}>
        <Icon name="mic" />
        <div><b>Microphone {voice?.microphone ? "found" : "unavailable"}</b><div className="small text-2">{voice?.microphone_detail}</div></div>
      </div>
      <div className="callout">
        <Icon name="info" />
        <span>Speak in any language — Hindi, Hinglish, English. Labels are translated to English on this computer, then
          shown for you to check; you can edit the text if a name was misheard.</span>
      </div>
      <div className="field">
        <label>Push-to-talk</label>
        <div className="small text-2">Hold <span className="kbd">Ctrl</span> + <span className="kbd">Space</span> while Folio is focused, or the mic button.</div>
        {os === "linux" ? (
          <>
            <div className="small text-2">Anywhere: <span className="kbd">Ctrl</span> + <span className="kbd">Alt</span> + <span className="kbd">Space</span> on X11. On Wayland (GNOME, KDE, Hyprland) apps cannot grab global keys — bind one in your desktop's shortcut settings to:</div>
            <div className="excerpt mono">folio-core voice toggle</div>
            <div className="tiny muted">Hyprland example: <span className="mono">bind = SUPER, V, exec, folio-core voice toggle</span></div>
          </>
        ) : (
          <div className="small text-2">Anywhere: hold <span className="kbd">Ctrl</span> + <span className="kbd">Alt</span> + <span className="kbd">Space</span>, even when Folio is in the background.</div>
        )}
      </div>
    </div>
  );
}

function PrivacyTab() {
  const { data: status } = useStatus();
  const actions = useSettingsActions();
  const cloud = !!status?.cloud_enabled;
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div>
        <h2>Privacy</h2>
        <p className="lead small text-2" style={{ margin: 0 }}>Your files are never copied, moved or modified. Everything is processed on this computer unless you allow a hosted AI model.</p>
      </div>
      <div className={`callout ${cloud ? "warn" : "ok"}`}>
        <Icon name={cloud ? "cloud" : "shield"} />
        <div className="grow">
          <b>{cloud ? "Cloud allowed for this project" : "Local only"}</b>
          <div className="small text-2">{cloud ? `File text may be sent to ${status?.llm.label ?? "the configured provider"} for extraction.` : "AI processing stays on this device. Optional Google Drive backups are sent only when you choose Back up now."}</div>
        </div>
        <button type="button" className="btn sm" onClick={() => actions.setCloud.mutate(!cloud)}>{cloud ? "Go local only" : "Allow cloud"}</button>
      </div>
      <div className="field"><label>Data folder</label><div className="excerpt mono">{status?.data_dir}</div></div>
      <div className="small text-2">API keys live in <span className="mono">secrets.json</span> in that folder (readable only by you). They are never stored in the database, the history, or exports.</div>
    </div>
  );
}

function HintsTab() {
  const { client } = useApi();
  const { data } = useSchema();
  const { data: status } = useStatus();
  const [text, setText] = useState("");
  useEffect(() => setText(data?.yaml ?? ""), [data?.yaml]);
  const save = useAction(async (yaml: string) => unwrap(await client.PUT("/api/schema", { body: { yaml } })), "Type hints saved as a new version");
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div>
        <h2>Type hints <span className="badge">v{data?.version}</span></h2>
        <p className="lead small text-2" style={{ margin: 0 }}>
          There are no fixed categories — any type or relation the AI or you name is accepted. Hints only help: colours,
          spoken phrases ("signed" → signed_on), date parsing and suggestions for the AI.
        </p>
      </div>
      {!!status?.types.length && (
        <div className="small text-2">Types in use: {status.types.join(", ")}</div>
      )}
      <textarea className="input schema" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      <div className="row"><span className="spacer" /><button type="button" className="btn primary" onClick={() => save.mutate(text)}><Icon name="check" /> Save new version</button></div>
    </div>
  );
}

function DataTab() {
  const { conn } = useApi();
  const actions = useSettingsActions();
  const importBackup = useAction(async (file: File) => {
    if (file.size > 256 * 1024 * 1024) throw new Error("Choose a JSON backup smaller than 256 MB.");
    const response = await fetch(`${conn.baseUrl}/api/import/json`, {
      method: "POST", headers: { Authorization: `Bearer ${conn.token}`, "Content-Type": "application/json" },
      body: await file.text(),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail ?? "Could not import the local backup.");
    return result;
  }, "Backup imported into your local project");
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div>
        <h2>Data</h2>
        <p className="lead small text-2" style={{ margin: 0 }}>Your files, knowledge and search index stay on this device. No Folio server or storage account is involved. Google Drive backup is optional and uses your own credentials.</p>
      </div>
      <div className="field">
        <label>Export</label>
        {EXPORT_FORMATS.map((f) => (
          <div key={f.id} className="file-chip" onClick={() => exportFile(conn, f).then((ok) => ok && toast(`Exported ${f.file}`)).catch((e: Error) => toast(e.message, "error"))}>
            <Icon name="download" />
            <div className="grow"><b>{f.title}</b><div className="small text-2">{f.text}</div></div>
          </div>
        ))}
      </div>
      <div className="field">
        <label htmlFor="local-backup">Restore a local JSON backup (empty project only)</label>
        <input id="local-backup" type="file" accept="application/json,.json" disabled={importBackup.isPending} onChange={(event) => {
          const file = event.target.files?.[0]; if (file) importBackup.mutate(file);
          event.target.value = "";
        }} />
        <p className="small text-2">This reads the backup on this device. It is not uploaded to a Folio server or Google Drive.</p>
      </div>
      <div className="field">
        <label>Maintenance</label>
        <div className="row">
          <button type="button" className="btn" onClick={() => actions.extractAll.mutate(undefined)}><Icon name="sparkles" /> Re-run extraction</button>
          <button type="button" className="btn" onClick={() => window.confirm("Rebuild the search index? Every file is re-read; your knowledge is not touched.") && actions.rebuildIndex.mutate(undefined)}>
            <Icon name="refresh" /> Rebuild search index
          </button>
        </div>
      </div>
    </div>
  );
}
