/**
 * Live updates from the core (server-sent events). Any ledger change invalidates the knowledge
 * queries, so the graph, swimlane, timeline, table and entity card all refresh together (FR-6).
 */
import { authedUrl } from "@folio/api-client";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { setVoiceRecording } from "@/state/selection";
import { useApi } from "./client";

type CoreEvent =
  | { type: "ledger"; action: string; tables: string[] }
  | { type: "job" }
  | { type: "source" }
  | { type: "voice"; recording: boolean }
  | { type: "label"; label_id: string }
  | { type: "review" };

const KNOWLEDGE_KEYS = ["entities", "card", "claims", "claim", "claimHistory", "graph", "timeline", "swimlane", "review", "history", "search", "schema", "status"];

export function useCoreEvents(): void {
  const { conn } = useApi();
  const qc = useQueryClient();

  useEffect(() => {
    const pending = new Set<string>();
    let timer: number | undefined;
    const flush = () => {
      timer = undefined;
      for (const key of pending) void qc.invalidateQueries({ queryKey: [key] });
      pending.clear();
    };
    const schedule = (...keys: string[]) => {
      keys.forEach((k) => pending.add(k));
      timer ??= window.setTimeout(flush, 150); // coalesce bursts (e.g. extraction of a big file)
    };

    const es = new EventSource(authedUrl(conn, "/api/events/stream"));
    es.onmessage = (msg) => {
      const ev = JSON.parse(msg.data) as CoreEvent;
      switch (ev.type) {
        case "ledger":
          schedule(...KNOWLEDGE_KEYS, ...(ev.tables.includes("roots") ? ["roots", "sources"] : []));
          break;
        case "job":
          schedule("jobs", "status");
          break;
        case "source":
          schedule("sources", "source", "chunks", "status");
          break;
        case "voice":
          setVoiceRecording(ev.recording);
          schedule("status");
          break;
        case "review":
          schedule("review");
          break;
        default:
          break;
      }
    };
    return () => {
      es.close();
      if (timer) window.clearTimeout(timer);
    };
  }, [conn, qc]);
}
