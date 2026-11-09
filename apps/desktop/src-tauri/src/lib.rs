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
    tauri::async_runtime::spawn_blocking(move || sidecar.connection(Duration::from_secs(2)))
        .await
        .map_err(|e| e.to_string())?
}

/// Write an export the user chose a location for (path comes from the native save dialog).
#[tauri::command]
fn save_file(path: String, contents: Vec<u8>) -> Result<(), String> {
    use std::io::Write;
    let target = std::path::Path::new(&path);
    let parent = target.parent().ok_or("invalid export location")?;
    let temp = parent.join(format!(".folio-export-{}.tmp", uuid::Uuid::new_v4()));
    let result = (|| -> std::io::Result<()> {
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&temp)?;
        if let Ok(existing) = std::fs::metadata(target) {
            file.set_permissions(existing.permissions())?;
        }
        file.write_all(&contents)?;
        file.sync_all()?;
        std::fs::rename(&temp, target)
    })();
    if result.is_err() { let _ = std::fs::remove_file(&temp); }
    result.map_err(|e| format!("cannot write {path}: {e}"))
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn exports_are_private_and_preserve_existing_permissions() {
        let folder = std::env::temp_dir().join(format!("folio-export-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&folder).unwrap();
        let target = folder.join("backup.json");
        save_file(target.to_string_lossy().into_owned(), b"first".to_vec()).unwrap();
        assert_eq!(std::fs::metadata(&target).unwrap().permissions().mode() & 0o077, 0);
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o640)).unwrap();
        save_file(target.to_string_lossy().into_owned(), b"second".to_vec()).unwrap();
        assert_eq!(std::fs::read(&target).unwrap(), b"second");
        assert_eq!(std::fs::metadata(&target).unwrap().permissions().mode() & 0o777, 0o640);
        std::fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn failed_export_keeps_existing_target_and_cleans_temporary_file() {
        let folder = std::env::temp_dir().join(format!("folio-export-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&folder).unwrap();
        let target = folder.join("directory");
        std::fs::create_dir(&target).unwrap();
        assert!(save_file(target.to_string_lossy().into_owned(), b"fixture".to_vec()).is_err());
        assert!(target.is_dir());
        assert_eq!(std::fs::read_dir(&folder).unwrap().count(), 1);
        std::fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn only_google_authorization_can_open_the_system_browser() {
        assert!(open_google_auth("https://example.com/".into()).is_err());
        assert!(open_google_auth("file:///tmp/fixture".into()).is_err());
    }
}

#[tauri::command]
fn open_google_auth(url: String) -> Result<(), String> {
    if !url.starts_with("https://accounts.google.com/o/oauth2/v2/auth?") {
        return Err("only Google authorization URLs are allowed".into());
    }
    #[cfg(target_os = "linux")]
    let mut command = std::process::Command::new("xdg-open");
    #[cfg(target_os = "macos")]
    let mut command = std::process::Command::new("open");
    #[cfg(target_os = "windows")]
    let mut command = { let mut c = std::process::Command::new("rundll32.exe"); c.arg("url.dll,FileProtocolHandler"); c };
    command.arg(url).spawn().map(|_| ()).map_err(|e| format!("cannot open system browser: {e}"))
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
        .invoke_handler(tauri::generate_handler![core_connection, save_file, open_google_auth])
        .build(tauri::generate_context!())
        .expect("error while building Folio");

    app.run(|handle, event| {
        if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
            handle.state::<Sidecar>().stop();
        }
    });
}
