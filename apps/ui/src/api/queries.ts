/**
 * Data hooks. Reads are react-query queries keyed by resource; the SSE stream (events.ts)
 * invalidates them whenever the ledger changes, so every view re-renders from the same claims.
 * Mutations call the typed client and report failures as toasts.
 */
import type { Claim, components, Label } from "@folio/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "@/state/toast";
import { unwrap, useApi } from "./client";

type S = components["schemas"];

export function useStatus() {
  const { client } = useApi();
  return useQuery({ queryKey: ["status"], queryFn: async () => unwrap(await client.GET("/api/status")) });
}

export function useRoots() {
  const { client } = useApi();
  return useQuery({ queryKey: ["roots"], queryFn: async () => unwrap(await client.GET("/api/roots")) });
}

export function useSources() {
  const { client } = useApi();
  return useQuery({ queryKey: ["sources"], queryFn: async () => unwrap(await client.GET("/api/sources")) });
}

export function useFilePage(q: string, offset: number) {
  const { client } = useApi();
  return useQuery({ queryKey: ["files", q, offset], queryFn: async () =>
    unwrap(await client.GET("/api/files", { params: { query: { q, offset, limit: 100 } } })) });
}

export function useSource(id: string | null | undefined) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["source", id],
    enabled: !!id,
    queryFn: async () => unwrap(await client.GET("/api/sources/{source_id}", { params: { path: { source_id: id! } } })),
  });
}

export function useChunks(sourceId: string | null | undefined) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["chunks", sourceId],
    enabled: !!sourceId,
    queryFn: async () =>
      unwrap(await client.GET("/api/sources/{source_id}/chunks", { params: { path: { source_id: sourceId! } } })),
  });
}

export function useEntities(q: string, types?: string[]) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["entities", q, types],
    queryFn: async () => unwrap(await client.GET("/api/entities", { params: { query: { q, type: types, limit: 50 } } })),
  });
}

export function useEntityCard(id: string | null | undefined) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["card", id],
    enabled: !!id,
    queryFn: async () => unwrap(await client.GET("/api/entities/{entity_id}", { params: { path: { entity_id: id! } } })),
  });
}

export interface TableFilter {
  entity_id?: string;
  status?: string[];
  predicate?: string;
  entity_type?: string;
  include_mentions?: boolean;
}

export function useTable(filter: TableFilter, offset = 0, order = "recent") {
  const { client } = useApi();
  return useQuery({
    queryKey: ["claims", "table", filter, offset, order],
    queryFn: async () => unwrap(await client.GET("/api/views/table", { params: { query: { ...filter, limit: 100, offset, order } } })),
  });
}

export function useClaim(id: string | null | undefined) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["claim", id],
    enabled: !!id,
    queryFn: async () => unwrap(await client.GET("/api/claims/{claim_id}", { params: { path: { claim_id: id! } } })),
  });
}

export function useClaimHistory(id: string | null | undefined) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["claimHistory", id],
    enabled: !!id,
    queryFn: async () =>
      unwrap(await client.GET("/api/claims/{claim_id}/history", { params: { path: { claim_id: id! } } })),
  });
}

export function useGraph(entityId: string | null, depth: number, includeMentions: boolean, includeRejected: boolean) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["graph", entityId, depth, includeMentions, includeRejected],
    queryFn: async () =>
      unwrap(
        await client.GET("/api/views/graph", {
          params: {
            query: {
              entity_id: entityId ?? undefined,
              depth,
              include_mentions: includeMentions,
              include_rejected: includeRejected,
            },
          },
        }),
      ),
  });
}

export function useTimeline(entityId: string | null) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["timeline", entityId],
    enabled: !!entityId,
    queryFn: async () =>
      unwrap(await client.GET("/api/views/timeline/{entity_id}", { params: { path: { entity_id: entityId! } } })),
  });
}

export function useSwimlane(groupBy: "entity" | "type", types?: string[]) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["swimlane", groupBy, types],
    queryFn: async () =>
      unwrap(await client.GET("/api/views/swimlane", { params: { query: { group_by: groupBy, type: types } } })),
  });
}

export function useLabel(id: string | null | undefined) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["label", id],
    enabled: !!id,
    queryFn: async () => unwrap(await client.GET("/api/labels/{label_id}", { params: { path: { label_id: id! } } })),
  });
}

export function useReview() {
  const { client } = useApi();
  return useQuery({ queryKey: ["review"], queryFn: async () => unwrap(await client.GET("/api/review")) });
}

export function useJobs() {
  const { client } = useApi();
  return useQuery({
    queryKey: ["jobs"],
    queryFn: async () => unwrap(await client.GET("/api/jobs", { params: { query: { limit: 200 } } })),
  });
}

export function useHistory() {
  const { client } = useApi();
  return useQuery({
    queryKey: ["history"],
    queryFn: async () => unwrap(await client.GET("/api/history", { params: { query: { limit: 100 } } })),
  });
}

export function useSchema() {
  const { client } = useApi();
  return useQuery({ queryKey: ["schema"], queryFn: async () => unwrap(await client.GET("/api/schema")), staleTime: 60_000 });
}

export function useSearch(q: string) {
  const { client } = useApi();
  return useQuery({
    queryKey: ["search", q],
    enabled: q.trim().length > 1,
    queryFn: async () => unwrap(await client.GET("/api/search", { params: { query: { q, k: 10 } } })),
  });
}

export function useLlmSettings() {
  const { client } = useApi();
  return useQuery({ queryKey: ["llm"], queryFn: async () => unwrap(await client.GET("/api/llm")) });
}

export function useSettingsActions() {
  const { client } = useApi();
  return {
    saveLlm: useAction(async (body: S["LLMSettingsBody"]) => unwrap(await client.PUT("/api/llm", { body })), "AI model saved"),
    removeLlm: useAction(async () => unwrap(await client.DELETE("/api/llm")), "Back to offline extraction"),
    testLlm: useAction(async () => unwrap(await client.POST("/api/llm/test"))),
    listModels: useAction(async (body: S["ModelsBody"]) => unwrap(await client.POST("/api/llm/models", { body }))),
    extractAll: useAction(async () => unwrap(await client.POST("/api/extract/all")), "Extraction started for all files"),
    downloadSpeech: useAction(async () => unwrap(await client.POST("/api/speech/download")), "Downloading the speech model"),
    setCloud: useAction(async (enabled: boolean) => unwrap(await client.PUT("/api/settings/cloud", { body: { enabled } }))),
    rebuildIndex: useAction(async () => unwrap(await client.POST("/api/index/rebuild")), "Re-indexing all files"),
  };
}

/** Every write: run, toast on failure, refresh caches (SSE also refreshes other windows/views). */
export function useAction<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>, success?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      if (success) toast(success);
      void qc.invalidateQueries();
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
}

/** All knowledge-graph writes in one place. */
export function useKnowledgeActions() {
  const { client } = useApi();
  return {
    setClaimStatus: useAction(async (a: { ids: string[]; status: "verified" | "rejected" | "proposed" }) =>
      unwrap(await client.POST("/api/claims/status", { body: { claim_ids: a.ids, status: a.status } })),
    ),
    editClaim: useAction(async (a: { id: string; changes: S["EditClaim"] }) =>
      unwrap(await client.PATCH("/api/claims/{claim_id}", { params: { path: { claim_id: a.id } }, body: a.changes })),
    ),
    createClaim: useAction(async (body: S["CreateClaim"]) => unwrap(await client.POST("/api/claims", { body })), "Fact added"),
    createEntity: useAction(async (body: S["CreateEntity"]) => unwrap(await client.POST("/api/entities", { body }))),
    updateEntity: useAction(async (a: { id: string; changes: S["UpdateEntity"] }) =>
      unwrap(await client.PATCH("/api/entities/{entity_id}", { params: { path: { entity_id: a.id } }, body: a.changes })),
    ),
    merge: useAction(
      async (a: { keep: string; merge: string }) =>
        unwrap(await client.POST("/api/entities/merge", { body: { keep_id: a.keep, merge_id: a.merge } })),
      "Merged — Ctrl+Z to undo",
    ),
    split: useAction(async (a: { id: string; name: string; claimIds: string[] }) =>
      unwrap(
        await client.POST("/api/entities/{entity_id}/split", {
          params: { path: { entity_id: a.id } },
          body: { name: a.name, claim_ids: a.claimIds },
        }),
      ),
    ),
    addAlias: useAction(async (a: { id: string; alias: string }) =>
      unwrap(await client.POST("/api/entities/{entity_id}/aliases", { params: { path: { entity_id: a.id } }, body: { alias: a.alias } })),
    ),
    removeAlias: useAction(async (a: { id: string; alias: string }) =>
      unwrap(
        await client.DELETE("/api/entities/{entity_id}/aliases", {
          params: { path: { entity_id: a.id }, query: { alias: a.alias } },
        }),
      ),
    ),
    undo: useAction(async (groupId?: string) => unwrap(await client.POST("/api/undo", { body: { group_id: groupId ?? null } })), "Undone"),
    redo: useAction(async () => unwrap(await client.POST("/api/redo")), "Redone"),
  };
}

export function useLabelActions(onLabel: (l: Label | null) => void) {
  const { client } = useApi();
  return {
    typed: useAction(async (a: { transcript: string; target: S["Target"] }) => {
      const label = unwrap(await client.POST("/api/labels", { body: { ...a.target, transcript: a.transcript } }));
      onLabel(label);
      return label;
    }),
    start: useAction(async (target: S["Target"]) => unwrap(await client.POST("/api/voice/start", { body: target }))),
    stop: useAction(async () => {
      const label = unwrap(await client.POST("/api/voice/stop"));
      onLabel(label);
      return label;
    }),
    revise: useAction(async (a: { id: string; transcript: string }) => {
      const label = unwrap(
        await client.POST("/api/labels/{label_id}/transcript", {
          params: { path: { label_id: a.id } },
          body: { transcript: a.transcript },
        }),
      );
      onLabel(label);
      return label;
    }),
    answer: useAction(async (a: { id: string; question: string; value: string }) => {
      const label = unwrap(
        await client.POST("/api/labels/{label_id}/answer", {
          params: { path: { label_id: a.id } },
          body: { question_id: a.question, value: a.value },
        }),
      );
      onLabel(label);
      return label;
    }),
    confirm: useAction(async (id: string) => {
      const label = unwrap(await client.POST("/api/labels/{label_id}/confirm", { params: { path: { label_id: id } } }));
      onLabel(null);
      return label;
    }, "Label applied — Ctrl+Z to undo"),
    cancel: useAction(async (id: string) => {
      const label = unwrap(await client.POST("/api/labels/{label_id}/cancel", { params: { path: { label_id: id } } }));
      onLabel(null);
      return label;
    }),
  };
}

export type { Claim };
