/** Pure helpers for drops (kept free of React so they are easy to test). */
import type { Drop } from "@folio/api-client";

export type DropFile = NonNullable<Drop["files"]>[number];

/** Files grouped by their AI/virtual folder, in first-seen order; unassigned -> "Unsorted". */
export function groupByFolder(drop: Pick<Drop, "files">): [string, DropFile[]][] {
  const out = new Map<string, DropFile[]>();
  for (const f of drop.files ?? []) {
    const key = f.folder ?? "Unsorted";
    out.set(key, [...(out.get(key) ?? []), f]);
  }
  return Array.from(out.entries());
}

/** One card per project: the most recent organized drop for each project. */
export function latestProjects<T extends Pick<Drop, "status" | "project">>(drops: T[]): T[] {
  const seen = new Map<string, T>();
  for (const d of drops) if (d.status === "organized" && d.project && !seen.has(d.project.id)) seen.set(d.project.id, d);
  return Array.from(seen.values());
}
