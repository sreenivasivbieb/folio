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

/** What the file-count pill says: the real outcome once the import finished, the estimate before. */
export function dropCountLabel(drop: Pick<Drop, "status" | "file_count" | "skipped" | "import_stats">): string {
  const s = drop.import_stats;
  if (!s || drop.status === "importing") {
    const n = drop.file_count;
    return `${n} file${n === 1 ? "" : "s"}${drop.status === "importing" ? " · importing…" : ""}`;
  }
  const [added, dupes, failed] = [s.imported ?? 0, s.duplicates ?? 0, s.failed ?? 0];
  const n = added + dupes;
  const parts = [`${n} file${n === 1 ? "" : "s"}`];
  if (dupes) parts.push(`${dupes} already in Folio`);
  if (failed) parts.push(`${failed} failed`);
  return parts.join(" · ");
}
