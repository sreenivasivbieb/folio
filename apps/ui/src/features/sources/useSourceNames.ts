import { useMemo } from "react";
import { useSources } from "@/api/queries";
import { basename } from "@/lib/format";

/** source id -> file name, for evidence links. */
export function useSourceNames(): Record<string, string> {
  const { data } = useSources();
  return useMemo(() => Object.fromEntries((data ?? []).map((s) => [s.id, basename(s.path)])), [data]);
}
