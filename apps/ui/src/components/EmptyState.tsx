import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export function EmptyState({ icon, title, children, actions, tag }: {
  icon: IconName;
  /** Light heading; wrap the key word in <b> for the bold accent. */
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  /** Two-part pill above the title: [label] text. */
  tag?: [string, string];
}) {
  return (
    <div className="empty-state">
      {tag ? <span className="tag-pill"><b>{tag[0]}</b>{tag[1]}</span> : <div className="glyph"><Icon name={icon} size={24} /></div>}
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
