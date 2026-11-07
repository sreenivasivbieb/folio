import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

/** Render one PDF page and highlight the evidence rect (PDF points, top-left origin). */
export function PdfPage({ url, page, rect, width = 370 }: { url: string; page: number; rect?: number[] | null; width?: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [scale, setScale] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [pages, setPages] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const task = pdfjs.getDocument({ url });
    (async () => {
      try {
        const doc = await task.promise;
        if (cancelled) return;
        setPages(doc.numPages);
        const p = await doc.getPage(Math.min(Math.max(page, 1), doc.numPages));
        const base = p.getViewport({ scale: 1 });
        const s = width / base.width;
        const viewport = p.getViewport({ scale: s * window.devicePixelRatio });
        const el = canvas.current;
        if (!el || cancelled) return;
        el.width = viewport.width;
        el.height = viewport.height;
        el.style.width = `${viewport.width / window.devicePixelRatio}px`;
        await p.render({ canvasContext: el.getContext("2d")!, viewport }).promise;
        setScale(s);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [url, page, width]);

  if (error) return <div className="muted">Cannot render PDF: {error}</div>;
  return (
    <div>
      <div className="small muted" style={{ marginBottom: 4 }}>Page {page}{pages ? ` of ${pages}` : ""}</div>
      <div className="pdf-wrap">
        <canvas ref={canvas} />
        {rect && (
          <div
            className="highlight"
            style={{
              left: rect[0] * scale - 2,
              top: rect[1] * scale - 2,
              width: (rect[2] - rect[0]) * scale + 4,
              height: (rect[3] - rect[1]) * scale + 4,
            }}
          />
        )}
      </div>
    </div>
  );
}
