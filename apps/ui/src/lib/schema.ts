/** Typed view of the user-editable schema (GET /api/schema returns it as JSON). */
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

const FALLBACK = "#888888";

export function useSchemaDef(): SchemaDef | null {
  const { data } = useSchema();
  return (data?.schema as unknown as SchemaDef) ?? null;
}

export function typeColor(schema: SchemaDef | null, type: string): string {
  return schema?.entity_types[type]?.color ?? FALLBACK;
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
