import { createStore } from "./store";

export interface Toast {
  id: number;
  text: string;
  tone: "info" | "error";
}

export const toasts = createStore<{ items: Toast[] }>({ items: [] });
let next = 1;

export function toast(text: string, tone: Toast["tone"] = "info") {
  const id = next++;
  toasts.set((s) => ({ items: [...s.items, { id, text, tone }] }));
  window.setTimeout(() => toasts.set((s) => ({ items: s.items.filter((t) => t.id !== id) })), tone === "error" ? 6000 : 3000);
}
