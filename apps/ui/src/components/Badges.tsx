import { confidenceBand } from "@/lib/format";
import { typeColor, useSchemaDef } from "@/lib/schema";

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${status}`}>{status}</span>;
}

export function Confidence({ value }: { value: number }) {
  return (
    <span className={`conf ${confidenceBand(value)}`} title="confidence">
      {Math.round(value * 100)}%
    </span>
  );
}

export function TypeDot({ type }: { type: string }) {
  const schema = useSchemaDef();
  return <span className="dot" style={{ background: typeColor(schema, type) }} title={type} />;
}

export function EntityName({ name, type, onClick }: { name: string; type: string; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="row"
      style={{ display: "inline-flex", border: 0, background: "none", padding: 0, cursor: onClick ? "pointer" : "default", fontWeight: 600 }}
    >
      <TypeDot type={type} />
      {name}
    </button>
  );
}
