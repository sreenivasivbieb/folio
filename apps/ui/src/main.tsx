import type { Connection } from "@folio/api-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ApiProvider } from "@/api/client";
import { inTauri, resolveConnection } from "@/api/connection";
import { checkCore } from "@/api/health";
import { Layout } from "@/app/Layout";
import { initTheme } from "@/lib/theme";
import { Logo } from "@/components/Logo";
import "./styles.css";

initTheme(); // before the first paint, so there is no flash of the wrong theme

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
      <div className="splash">
        <Logo size={112} animated={!failed} />
        <div className="splash-word">Folio</div>
        {!failed && <>
          <div className="splash-bar"><div /></div>
          <div className="splash-hint"><SplashHint /></div>
        </>}
        {failed && <h3 className="splash-title">Waiting for the Folio <b>backend</b></h3>}
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

const HINTS = ["Opening your vault…", "Loading your knowledge…", "Warming up search…"];

/** Rotates a short status line while the local core starts. */
function SplashHint() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setI((n) => (n + 1) % HINTS.length), 1400);
    return () => window.clearInterval(t);
  }, []);
  return <span key={i} className="splash-hint-text">{HINTS[i]}</span>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Boot />
  </StrictMode>,
);
