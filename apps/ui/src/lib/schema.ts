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
const PALETTE = ["#6e6ef2", "#e5484d", "#30a46c", "#f76b15", "#8e4ec6", "#0090ff", "#d6409f",
  "#12a594", "#ad7f58", "#e54666", "#5b5bd6", "#978365", "#3e63dd", "#46a758"];

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
