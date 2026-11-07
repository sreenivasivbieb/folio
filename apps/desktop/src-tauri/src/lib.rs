//! Folio desktop shell (Tauri 2).
//!
//! Deliberately thin. It owns only what needs the OS:
//!   * the window and native file/save dialogs,
//!   * starting and supervising the core sidecar (see `sidecar.rs`),
//!   * a best-effort global push-to-talk hotkey (works on Windows, macOS and X11; on Wayland
//!     compositors such as Hyprland bind a key to `folio-core voice toggle` instead — ADR-0003).
//! Everything else — files, models, the database — lives in the core service.

mod sidecar;

use sidecar::{Connection, Sidecar};
use std::time::Duration;
use tauri::{Emitter, Manager, RunEvent};
use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutState};

/// The UI calls this once at startup to learn where the core listens and its session token.
#[tauri::command]
async fn core_connection(sidecar: tauri::State<'_, Sidecar>) -> Result<Connection, String> {
    let sidecar = sidecar.inner().clone();
    tauri::async_runtime::spawn_blocking(move || sidecar.connection(Duration::from_secs(90)))
        .await
        .map_err(|e| e.to_string())?
}

/// Write an export the user chose a location for (path comes from the native save dialog).
#[tauri::command]
fn save_file(path: String, contents: Vec<u8>) -> Result<(), String> {
    std::fs::write(&path, contents).map_err(|e| format!("cannot write {path}: {e}"))
}

pub fn run() {
    let push_to_talk = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::Space);
    let sidecar = Sidecar::default();
    sidecar.start();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if shortcut == &push_to_talk {
                        let pressed = event.state() == ShortcutState::Pressed;
                        let _ = app.emit("folio://push-to-talk", pressed);
                    }
                })
                .build(),
        )
        .manage(sidecar)
        .setup(move |app| {
            use tauri_plugin_global_shortcut::GlobalShortcutExt;
            if let Err(e) = app.global_shortcut().register(push_to_talk) {
                log::warn!("global push-to-talk hotkey unavailable ({e}); use the in-app key or `folio-core voice toggle`");
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![core_connection, save_file])
        .build(tauri::generate_context!())
        .expect("error while building Folio");

    app.run(|handle, event| {
        if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
            handle.state::<Sidecar>().stop();
        }
    });
}
