/**
 * "A click on any item opens its evidence": the PDF page with the region highlighted, the video
 * at the exact second, the text span highlighted, the image region boxed, or the voice label.
 * Originals are streamed read-only by the core; the UI never touches files directly.
 */
import { authedUrl, type Chunk, type Evidence, type Locator } from "@folio/api-client";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useApi } from "@/api/client";
import { useChunks, useLabel, useSource } from "@/api/queries";
import { basename, locatorLabel } from "@/lib/format";
import { ui } from "@/state/selection";
import { PdfPage } from "./PdfPage";

function Highlighted({ text, quote }: { text: string; quote: string }) {
  const norm = (s: string) => s.replace(/\s+/g, " ").trim();
  const t = norm(text);
  const q = norm(quote);
  const i = q ? t.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (i < 0) return <div className="excerpt">{t}</div>;
  return (
    <div className="excerpt">
      {t.slice(0, i)}
      <mark>{t.slice(i, i + q.length)}</mark>
      {t.slice(i + q.length)}
    </div>
  );
}

function pickChunk(chunks: Chunk[], ev: Evidence): Chunk | undefined {
  const byId = chunks.find((c) => c.id === ev.chunk_id);
  if (byId) return byId;
  const loc = ev.locator;
  return chunks.find((c) => {
    const l = c.locator;
    if (loc.kind === "page") return l.page === loc.page && c.text.includes(ev.quote.slice(0, 40));
    if (loc.kind === "time") return (l.start ?? 0) <= (loc.start ?? 0) && (loc.start ?? 0) <= (l.end ?? 0);
    if (loc.kind === "text") return (l.line_start ?? 0) <= (loc.line_start ?? 0) && (loc.line_start ?? 0) <= (l.line_end ?? 0);
    return false;
  }) ?? chunks.find((c) => c.text.includes(ev.quote.slice(0, 40)));
}

function Media({ url, kind, start }: { url: string; kind: string; start?: number | null }) {
  const ref = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || start == null) return;
    const seek = () => {
      el.currentTime = start;
    };
    el.addEventListener("loadedmetadata", seek, { once: true });
    if (el.readyState >= 1) seek();
  }, [url, start]);
  return kind === "video" ? (
    <video ref={ref} src={url} controls style={{ width: "100%", borderRadius: 8 }} />
  ) : (
    <audio ref={ref} src={url} controls style={{ width: "100%" }} />
  );
}

function ImageRegion({ url, rect }: { url: string; rect?: number[] | null }) {
  const [scale, setScale] = useState(0);
  return (
    <div className="pdf-wrap">
      <img src={url} alt="" style={{ maxWidth: 370, display: "block" }} onLoad={(e) => setScale(e.currentTarget.width / e.currentTarget.naturalWidth)} />
      {rect && scale > 0 && (
        <div className="highlight" style={{ left: rect[0] * scale, top: rect[1] * scale, width: (rect[2] - rect[0]) * scale, height: (rect[3] - rect[1]) * scale }} />
      )}
    </div>
  );
}

function Frame({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <div className="evidence">
      <div className="row" style={{ marginBottom: 8 }}>
        <strong className="ellipsis">{title}</strong>
        <span className="spacer" />
        <button type="button" className="btn small" onClick={() => ui.set({ evidence: null, openSourceId: null })}>Close</button>
      </div>
      {children}
    </div>
  );
}

export function EvidenceViewer({ evidence }: { evidence: Evidence }) {
  const { conn } = useApi();
  const { data: detail } = useSource(evidence.source_id);
  const { data: chunks } = useChunks(evidence.source_id);
  const loc: Locator = evidence.locator;
  const { data: label } = useLabel(loc.kind === "label" ? loc.label_id : null);

  if (loc.kind === "label" || !evidence.source_id) {
    return (
      <Frame title={label?.audio_path ? "Voice label" : "Typed label"}>
        <div className="excerpt">“{evidence.quote}”</div>
        {label?.audio_path && <div style={{ marginTop: 8 }}><Media url={authedUrl(conn, `/api/labels/${label.id}/audio`)} kind="audio" /></div>}
        {label && <div className="small muted" style={{ marginTop: 8 }}>{new Date(label.created_at).toLocaleString()} · {label.status}</div>}
      </Frame>
    );
  }
  if (!detail) return <Frame title="Loading…">{null}</Frame>;
  const src = detail.source;
  const fileUrl = authedUrl(conn, `/api/sources/${src.id}/file`);
  const chunk = chunks ? pickChunk(chunks, evidence) : undefined;

  return (
    <Frame title={<span title={src.path}>{basename(src.path)} · {locatorLabel(loc)}</span>}>
      {src.kind === "pdf" && <PdfPage url={fileUrl} page={loc.page ?? 1} rect={loc.rect} />}
      {(src.kind === "video" || src.kind === "audio") && <Media url={fileUrl} kind={src.kind} start={loc.start} />}
      {src.kind === "image" && <ImageRegion url={fileUrl} rect={loc.rect} />}
      <div style={{ marginTop: 10 }}>
        <div className="small muted" style={{ marginBottom: 4 }}>Quoted span</div>
        <Highlighted text={chunk?.text ?? evidence.quote} quote={evidence.quote} />
      </div>
    </Frame>
  );
}

/** A whole file opened from the sources list: its chunks with locators. */
export function SourceViewer({ sourceId }: { sourceId: string }) {
  const { conn } = useApi();
  const { data: detail } = useSource(sourceId);
  const { data: chunks } = useChunks(sourceId);
  if (!detail) return <Frame title="Loading…">{null}</Frame>;
  const src = detail.source;
  const fileUrl = authedUrl(conn, `/api/sources/${src.id}/file`);
  return (
    <Frame title={<span title={src.path}>{basename(src.path)}</span>}>
      <div className="row small muted" style={{ marginBottom: 8 }}>
        <span className="badge">{src.kind}</span> {src.status} · {detail.chunks} chunks · {(src.size / 1024).toFixed(0)} KB
      </div>
      {src.error && <div className="question">{src.error}</div>}
      {src.kind === "pdf" && <PdfPage url={fileUrl} page={1} />}
      {(src.kind === "video" || src.kind === "audio") && <Media url={fileUrl} kind={src.kind} />}
      {src.kind === "image" && <ImageRegion url={fileUrl} />}
      <div className="stack" style={{ marginTop: 10 }}>
        {(chunks ?? []).map((c) => (
          <div key={c.id}>
            <div className="small muted">{locatorLabel(c.locator)}</div>
            <div className="excerpt">{c.text}</div>
          </div>
        ))}
      </div>
      <p className="small muted">Tip: with this file selected, speak or type a label, e.g. “This PDF is the Acme contract, Priya owns it”.</p>
    </Frame>
  );
}
