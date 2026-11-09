/** Move or copy — asked every time, never assumed. */
import { Icon, type IconName } from "@/components/Icon";

export type Mode = "move" | "copy";

export function ModeChoice({ value, onChange, move, copy }: {
  value: Mode | null;
  onChange: (m: Mode) => void;
  move: string;
  copy: string;
}) {
  const option = (id: Mode, icon: IconName, title: string, text: string) => (
    <button type="button" className="choice" aria-pressed={value === id} onClick={() => onChange(id)}>
      <span className="choice-icon"><Icon name={icon} size={16} /></span>
      <b>{title}</b>
      <span>{text}</span>
    </button>
  );
  return (
    <div className="choice-grid">
      {option("move", "folder", "Move", move)}
      {option("copy", "layers", "Copy", copy)}
    </div>
  );
}
