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
    return <div className="empty" style={{ paddingTop: "30vh" }}>{error && !error.includes("fetch") ? error : "Starting Folio…"}</div>;
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
