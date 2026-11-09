/** Typed view of the type *hints* (open schema: any type is allowed; hints add colour and help). */
import { useSchema } from "@/api/queries";

export interface AttributeDef {
  type: string;
  description?: string;
  multi?: boolean;
}
export interface EntityTypeDef {
  description?: string;
  color: string;
  attributes: Record<string, AttributeDef>;
}
export interface RelationTypeDef {
  description?: string;
  source: string[];
  target: string[];
}
export interface SchemaDef {
  name: string;
  version: number;
  entity_types: Record<string, EntityTypeDef>;
  relation_types: Record<string, RelationTypeDef>;
}

// Distinct, readable on light and dark. New types get a stable colour from their name.
// Matches the app theme: blue, violet, pink first, then softer companions.
const PALETTE = ["#3d63f5", "#7c5cf6", "#ec4f9c", "#14b8a6", "#f59e0b", "#0ea5e9", "#a855f7",
  "#f43f5e", "#22c55e", "#6366f1", "#d946ef", "#f97316", "#06b6d4", "#84cc16"];

function hashColor(type: string): string {
  let h = 0;
  for (const ch of type.toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export function useSchemaDef(): SchemaDef | null {
  const { data } = useSchema();
  return (data?.schema as unknown as SchemaDef) ?? null;
}

export function typeColor(schema: SchemaDef | null, type: string): string {
  if (type === "Document") return "#8b8d98";
  return schema?.entity_types[type]?.color ?? hashColor(type);
}

/** Predicates the given entity type may have as subject: its attributes and allowed relations. */
export function predicatesFor(schema: SchemaDef | null, type: string) {
  if (!schema) return { attributes: [] as [string, AttributeDef][], relations: [] as [string, RelationTypeDef][] };
  const attributes = Object.entries(schema.entity_types[type]?.attributes ?? {});
  const relations = Object.entries(schema.relation_types).filter(
    ([, r]) => r.source.includes("*") || r.source.includes(type),
  );
  return { attributes, relations };
}
