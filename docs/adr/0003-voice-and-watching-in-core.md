# 0003 — Microphone capture and folder watching live in the core

**Context.** The proposal assigned the global push-to-talk hotkey, voice capture (in the webview)
and folder watching to the shell. In practice:

* On Linux, Tauri uses WebKitGTK, whose `getUserMedia` support is unreliable.
* On Wayland (e.g. Hyprland) applications cannot grab global keys at all.
* The core owns sources and content hashes; a watcher in Rust would have to relay every file
  event across the process boundary to the component that decides what to do.

**Decision.**

* Audio is captured in the core (`sounddevice`), stored next to the database as label evidence,
  and transcribed there. The UI only sends start/stop.
* Folder watching (`watchdog`, debounced) runs in the core, plus a rescan at startup.
* Push-to-talk: in-app hold key (Ctrl+Space) everywhere; a global hotkey from the shell
  (Ctrl+Alt+Space) where the OS allows it; and `folio-core voice toggle` for compositor bindings.

**Consequences.** Identical behaviour on all OSes; the shell stays thin. The core needs microphone
permission (macOS will prompt for the app bundle).
