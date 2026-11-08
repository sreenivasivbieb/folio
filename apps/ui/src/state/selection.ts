/**
 * UI state shared across panels: what is selected, which view is active, what evidence is open,
 * and the label being previewed. The current selection is also the *target* of voice labels
 * ("this is wrong", "merge these two" apply to whatever is selected).
 */
import type { Evidence, Label } from "@folio/api-client";
import { createStore } from "./store";

export type Selection =
  | { kind: "none" }
  | { kind: "entity"; ids: string[] }
  | { kind: "claim"; ids: string[] }
  | { kind: "source"; id: string };

export type ViewName = "graph" | "swimlane" | "timeline" | "table";
export type LeftTab = "sources" | "review" | "activity";
export type SettingsTab = "ai" | "voice" | "privacy" | "hints" | "data";

interface UiState {
  selection: Selection;
  focusEntity: string | null; // the entity the timeline / graph neighbourhood is about
  view: ViewName;
  leftTab: LeftTab;
  evidence: Evidence | null;
  openSourceId: string | null; // a whole file opened from the sources list
  label: Label | null; // label preview awaiting confirmation
  recording: boolean;
  modal: "none" | "search" | "settings";
  settingsTab: SettingsTab;
}

export const ui = createStore<UiState>({
  selection: { kind: "none" },
  focusEntity: null,
  view: "graph",
  leftTab: "sources",
  evidence: null,
  openSourceId: null,
  label: null,
  recording: false,
  modal: "none",
  settingsTab: "ai",
});

export function openSettings(tab: SettingsTab = "ai") {
  ui.set({ modal: "settings", settingsTab: tab });
}

export function selectEntity(id: string, additive = false) {
  ui.set((s) => {
    if (additive && s.selection.kind === "entity") {
      const ids = s.selection.ids.includes(id) ? s.selection.ids.filter((x) => x !== id) : [...s.selection.ids, id];
      return { selection: ids.length ? { kind: "entity", ids } : { kind: "none" } };
    }
    return { selection: { kind: "entity", ids: [id] }, focusEntity: id, evidence: null, openSourceId: null };
  });
}

export function selectClaims(ids: string[]) {
  ui.set({ selection: ids.length ? { kind: "claim", ids } : { kind: "none" } });
}

export function selectSource(id: string) {
  ui.set({ selection: { kind: "source", id }, openSourceId: id, evidence: null });
}

export function openEvidence(evidence: Evidence) {
  ui.set({ evidence, openSourceId: null });
}

export function setVoiceRecording(recording: boolean) {
  ui.set({ recording });
}

/** The label target derived from the selection. */
export function labelTarget(sel: Selection): { target_kind: "source" | "entity" | "claim" | "none"; target_ids: string[] } {
  switch (sel.kind) {
    case "source":
      return { target_kind: "source", target_ids: [sel.id] };
    case "entity":
      return { target_kind: "entity", target_ids: sel.ids };
    case "claim":
      return { target_kind: "claim", target_ids: sel.ids };
    default:
      return { target_kind: "none", target_ids: [] };
  }
}
