import { confidenceBand } from "@/lib/format";
import { typeColor, useSchemaDef } from "@/lib/schema";

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${status}`}>{status}</span>;
}

export function Confidence({ value }: { value: number }) {
  return (
    <span className={`conf ${confidenceBand(value)}`} title="Confidence">
      {Math.round(value * 100)}%
    </span>
  );
}

export function TypeDot({ type, size = 8 }: { type: string; size?: number }) {
  const schema = useSchemaDef();
  return <span className="dot" style={{ background: typeColor(schema, type), width: size, height: size }} title={type} />;
}

export function TypePill({ type }: { type: string }) {
  const schema = useSchemaDef();
  const color = typeColor(schema, type);
  return (
    <span className="type-pill" style={{ background: `color-mix(in srgb, ${color} 16%, transparent)`, color }}>
      <span className="dot" style={{ background: color }} />
      {type}
    </span>
  );
}

export function EntityName({ name, type, onClick }: { name: string; type: string; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} className="entity-link" disabled={!onClick}>
      <TypeDot type={type} />
      {name}
    </button>
  );
}
