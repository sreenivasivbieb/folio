/** Native file/folder pickers (desktop app). In a plain browser, paths are typed instead. */
import { inTauri } from "@/api/connection";

export async function pickPaths(directory: boolean): Promise<string[]> {
  if (inTauri) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const res = await open({ directory, multiple: true });
    return res == null ? [] : Array.isArray(res) ? res : [res];
  }
  const typed = window.prompt(directory ? "Folder path to add" : "File path(s) to add, one per line");
  return typed ? typed.split(/\r?\n/).map((s) => s.trim()).filter(Boolean) : [];
}

export async function pickFolder(): Promise<string | null> {
  if (inTauri) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const res = await open({ directory: true, multiple: false });
    return typeof res === "string" ? res : null;
  }
  return window.prompt("Folder to export to") || null;
}
