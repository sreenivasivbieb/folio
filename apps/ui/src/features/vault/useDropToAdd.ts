/** Drop files or folders anywhere on the desktop window to add them to Folio. */
import { useEffect, useState } from "react";
import { inTauri } from "@/api/connection";
import { openAdd, ui } from "@/state/selection";

export function useDropToAdd(): boolean {
  const [over, setOver] = useState(false);
  useEffect(() => {
    if (!inTauri) return;
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    void import("@tauri-apps/api/webview").then(({ getCurrentWebview }) =>
      getCurrentWebview().onDragDropEvent((e) => {
        const p = e.payload;
        if (p.type === "enter" || p.type === "over") setOver(true);
        else if (p.type === "leave") setOver(false);
        else if (p.type === "drop") {
          setOver(false);
          if (p.paths.length) openAdd(Array.from(new Set([...(ui.get().activeDrop ? [] : ui.get().pendingPaths), ...p.paths])));
        }
      }).then((u) => {
        if (cancelled) u();
        else unlisten = u;
      }),
    );
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);
  return over;
}
