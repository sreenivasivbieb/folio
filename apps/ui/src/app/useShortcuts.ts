/** Keyboard-first (NFR usability): undo everywhere, quick view switching, search. */
import { useEffect } from "react";
import { useKnowledgeActions } from "@/api/queries";
import { ui, type ViewName } from "@/state/selection";

const VIEWS: ViewName[] = ["graph", "swimlane", "timeline", "table"];

export function useShortcuts(): void {
  const { undo, redo } = useKnowledgeActions();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = !!(e.target as HTMLElement).closest("input, textarea, select, [contenteditable]");
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ui.set({ modal: "search" });
      } else if (mod && e.key.toLowerCase() === "z" && !typing) {
        e.preventDefault();
        if (e.shiftKey) redo.mutate(undefined);
        else undo.mutate(undefined);
      } else if (mod && e.key.toLowerCase() === "y" && !typing) {
        e.preventDefault();
        redo.mutate(undefined);
      } else if (!mod && !typing && ["1", "2", "3", "4"].includes(e.key)) {
        ui.set({ view: VIEWS[Number(e.key) - 1] });
      } else if (e.key === "Escape" && !typing) {
        ui.set({ evidence: null, openSourceId: null });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);
}
