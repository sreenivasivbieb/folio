import type { Connection } from "@folio/api-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ApiProvider } from "@/api/client";
import { resolveConnection } from "@/api/connection";
import { Layout } from "@/app/Layout";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: 1 } },
});

function Boot() {
  const [conn, setConn] = useState<Connection | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    (async () => {
      // The core may still be starting (first run applies migrations): wait for /api/health.
      for (let attempt = 0; attempt < 120 && !stop; attempt++) {
        try {
          const c = await resolveConnection();
          const res = await fetch(`${c.baseUrl}/api/health`);
          if (res.ok) {
            setConn(c);
            return;
          }
        } catch (e) {
          setError((e as Error).message);
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      setError("The Folio core service did not start. Check the logs in the app data folder.");
    })();
    return () => {
      stop = true;
    };
  }, []);

  if (!conn) {
    const failed = error && !error.includes("fetch");
    return (
      <div className="empty-state" style={{ height: "100%" }}>
        <div className="glyph" style={{ background: "linear-gradient(135deg, #6e6ef2, #4848c8)", color: "white" }}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={failed ? "" : "spin"}>
            <path d="M21 12a9 9 0 1 1-6.22-8.56" />
          </svg>
        </div>
        <h3>{failed ? "Folio could not start" : "Starting Folio…"}</h3>
        {failed && <p>{error} — is MongoDB running? Start it with <code>docker compose up -d</code> in the Folio folder.</p>}
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
