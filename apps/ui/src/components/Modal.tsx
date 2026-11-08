import { type ReactNode, useEffect } from "react";
import { Icon } from "./Icon";

export function Modal({ title, onClose, children, footer, wide, bare }: {
  title?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  /** No header/content padding: the child lays itself out (search palette, settings). */
  bare?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true">
        {title && (
          <header>
            {title}
            <span className="spacer" />
            <button type="button" className="btn ghost sm icon-only" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
          </header>
        )}
        {bare ? children : <div className="content">{children}</div>}
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}
