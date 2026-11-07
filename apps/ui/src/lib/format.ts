import type { Claim, Locator } from "@folio/api-client";

export function basename(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export function seconds(t: number | null | undefined): string {
  const s = Math.max(0, Math.floor(t ?? 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** "p.3", "1:05–1:12", "L10–14", "region", "voice label". */
export function locatorLabel(loc: Locator): string {
  switch (loc.kind) {
    case "page":
      return `p.${loc.page}`;
    case "time":
      return `${seconds(loc.start)}–${seconds(loc.end)}`;
    case "text":
      return loc.line_start === loc.line_end ? `L${loc.line_start}` : `L${loc.line_start}–${loc.line_end}`;
    case "region":
      return "region";
    case "label":
      return "voice label";
  }
}

export function predicateLabel(p: string): string {
  return p.replace(/_/g, " ");
}

export function valueText(c: Pick<Claim, "value">): string {
  if (c.value === null || c.value === undefined) return "";
  return typeof c.value === "string" ? c.value : JSON.stringify(c.value);
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function confidenceBand(c: number): "high" | "mid" | "low" {
  return c >= 0.75 ? "high" : c >= 0.5 ? "mid" : "low";
}
