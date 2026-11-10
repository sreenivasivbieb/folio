/** Keyboard-first (NFR usability): undo everywhere, quick view switching, search. */
import { useEffect } from "react";
import { useKnowledgeActions } from "@/api/queries";
import { ui, type ViewName } from "@/state/selection";

const VIEWS: ViewName[] = ["drop", "projects", "graph", "swimlane", "timeline"];

export function useShortcuts(): void {
  const { undo, redo } = useKnowledgeActions();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Only real text entry counts as typing: a focused checkbox or button must not swallow "/" or 1–4.
      const typing = !!(e.target as HTMLElement).closest(
        'input:not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="range"]), textarea, select, [contenteditable]');
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ui.set({ modal: "search" });
      } else if (e.key === "/" && !mod && !typing) {
        e.preventDefault(); // "/" opens search, like most apps
        ui.set({ modal: "search" });
      } else if (mod && e.key.toLowerCase() === "z" && !typing) {
        e.preventDefault();
        if (e.shiftKey) redo.mutate(undefined);
        else undo.mutate(undefined);
      } else if (mod && e.key.toLowerCase() === "y" && !typing) {
        e.preventDefault();
        redo.mutate(undefined);
      } else if (!mod && !typing && ["1", "2", "3", "4", "5"].includes(e.key)) {
        ui.set({ view: VIEWS[Number(e.key) - 1] });
      } else if (e.key === "Escape" && !typing) {
        ui.set({ evidence: null, openSourceId: null });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);
}
