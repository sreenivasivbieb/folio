import type { Connection } from "@folio/api-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ApiProvider } from "@/api/client";
import { inTauri, resolveConnection } from "@/api/connection";
import { checkCore } from "@/api/health";
import { Layout } from "@/app/Layout";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: 1 } },
});

function Boot() {
  const [conn, setConn] = useState<Connection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      let current: Connection | null = null;
      let failures = 0;
      while (!controller.signal.aborted) {
        try {
          const candidate: Connection = current ?? await resolveConnection();
          await checkCore(candidate, controller.signal, !current);
          if (controller.signal.aborted) return;
          if (!current) {
            current = candidate;
            setConn(candidate);
            setError(null);
            void queryClient.invalidateQueries();
          }
          failures = 0;
        } catch (e) {
          if (controller.signal.aborted) return;
          failures += 1;
          if (!current || failures >= 2) {
            current = null;
            setConn(null);
            setError((e as Error).message);
          }
        }
        await new Promise<void>((resolve) => {
          const timer = setTimeout(done, current ? 4000 : 1000);
          function done() { clearTimeout(timer); controller.signal.removeEventListener("abort", done); resolve(); }
          controller.signal.addEventListener("abort", done, { once: true });
        });
      }
    })();
    return () => controller.abort();
  }, [retry]);

  if (!conn) {
    const failed = !!error;
    return (
      <div className="empty-state" style={{ height: "100%" }}>
        <div className="glyph" style={{ background: "var(--brand-gradient)", color: "white" }}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={failed ? "" : "spin"}>
            <path d="M21 12a9 9 0 1 1-6.22-8.56" />
          </svg>
        </div>
        <h3>{failed ? "Waiting for the Folio backend" : "Starting Folio…"}</h3>
        {failed && <div className="stack" style={{ maxWidth: 600, textAlign: "center", gap: 12 }}>
          <p role="alert">{error}</p>
          <p>{inTauri
            ? (navigator.userAgent.includes("Windows") ? "Check %APPDATA%\\folio\\logs\\core.log" : "Check ~/.local/share/folio/logs/core.log") + " for the cause. Folio stores its data on this device."
            : "Run npm run dev from the Folio project folder to start the local backend and interface together."}</p>
          <p className="muted small">Folio retries automatically. Your files and knowledge are kept.</p>
          <button type="button" className="btn primary" onClick={() => { setError(null); setRetry((n) => n + 1); }}>Retry now</button>
        </div>}
      </div>
    );
  }
  return (
    <ApiProvider conn={conn}>
      <QueryClientProvider client={queryClient}>
        <Layout />
      </QueryClientProvider>
    </ApiProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Boot />
  </StrictMode>,
);
