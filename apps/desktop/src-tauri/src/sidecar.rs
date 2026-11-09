//! Starts and supervises the Python core service (the "sidecar").
//!
//! * A fresh random token is generated per session and passed via `FOLIO_TOKEN`.
//! * The core binds 127.0.0.1 on a random port and prints `FOLIO_READY {"port": N}` on stdout.
//! * If the core exits unexpectedly it is restarted (a few times), and the UI picks up the new
//!   connection through `core_connection`.
//! * `--exit-with-parent` makes the core exit if this shell dies without cleaning up.

use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::Duration;

const READY_PREFIX: &str = "FOLIO_READY ";
const MAX_RESTARTS: u32 = 3;

fn terminate_tree(child: &mut Child) {
    // PyInstaller has a bootloader and a Python worker. Stop their entire owned group.
    #[cfg(unix)]
    unsafe {
        libc::kill(-(child.id() as i32), libc::SIGKILL);
    }
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill").args(["/PID", &child.id().to_string(), "/T", "/F"]).status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Connection {
    pub base_url: String,
    pub token: String,
}

#[derive(Default)]
struct Inner {
    connection: Option<Connection>,
    child: Option<Child>,
    error: Option<String>,
    shutting_down: bool,
}

#[derive(Clone, Default)]
pub struct Sidecar {
    inner: Arc<(Mutex<Inner>, Condvar)>,
}

/// How to launch the core: `FOLIO_CORE_CMD` (dev override), the bundled binary next to this
/// executable (release), or `uv run` against the repo checkout (debug builds).
fn core_command() -> Command {
    if let Ok(cmd) = std::env::var("FOLIO_CORE_CMD") {
        let mut parts = cmd.split_whitespace();
        let mut c = Command::new(parts.next().expect("FOLIO_CORE_CMD is empty"));
        c.args(parts);
        return c;
    }
    let exe_dir = std::env::current_exe().ok().and_then(|p| p.parent().map(PathBuf::from));
    let bundled = exe_dir.map(|d| d.join(if cfg!(windows) { "folio-core.exe" } else { "folio-core" }));
    if let Some(path) = bundled.filter(|p| p.exists()) {
        return Command::new(path);
    }
    if !cfg!(debug_assertions) {
        // Installed builds must never fall back to the developer's source checkout.
        return Command::new("folio-core");
    }
    let repo_core = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../services/core");
    // Prefer the venv's entry point over `uv run`: then the child *is* the core, so killing it
    // and the core's exit-with-parent check work directly (uv would sit in between).
    let venv_bin = if cfg!(windows) { ".venv/Scripts/folio-core.exe" } else { ".venv/bin/folio-core" };
    if repo_core.join(venv_bin).exists() {
        return Command::new(repo_core.join(venv_bin));
    }
    let mut c = Command::new("uv");
    c.arg("run").arg("--project").arg(repo_core).arg("folio-core");
    c
}

impl Sidecar {
    pub fn start(&self) {
        let token = format!("{}{}", uuid::Uuid::new_v4().simple(), uuid::Uuid::new_v4().simple());
        let me = self.clone();
        thread::spawn(move || {
            let mut restarts = 0;
            loop {
                match me.spawn_once(&token) {
                    Ok(()) => {
                        let (lock, _) = &*me.inner;
                        // Poll so that stop() can kill the child from another thread meanwhile.
                        let status = loop {
                            let mut inner = lock.lock().unwrap();
                            match inner.child.as_mut().map(|c| c.try_wait()) {
                                Some(Ok(Some(status))) => break Some(status),
                                Some(Ok(None)) => {}
                                _ => break None,
                            }
                            drop(inner);
                            thread::sleep(Duration::from_millis(300));
                        };
                        let mut inner = lock.lock().unwrap();
                        inner.child = None;
                        inner.connection = None;
                        if inner.shutting_down {
                            return;
                        }
                        log::warn!("core exited: {status:?}");
                    }
                    Err(e) => {
                        let (lock, cvar) = &*me.inner;
                        let mut inner = lock.lock().unwrap();
                        if let Some(mut child) = inner.child.take() { terminate_tree(&mut child); }
                        if inner.shutting_down { return; }
                        log::error!("core failed to start: {e}");
                        inner.error = Some(e);
                        cvar.notify_all();
                    }
                }
                restarts += 1;
                if restarts > MAX_RESTARTS {
                    let (lock, cvar) = &*me.inner;
                    let mut inner = lock.lock().unwrap();
                    if inner.error.is_none() {
                        inner.error = Some("Core startup failed. See ~/.local/share/folio/logs/core.log.".into());
                    }
                    cvar.notify_all();
                    return;
                }
                thread::sleep(Duration::from_secs(1));
            }
        });
    }

    /// Register the child immediately so closing during startup also stops the worker.
    fn spawn_once(&self, token: &str) -> Result<(), String> {
        let mut cmd = core_command();
        cmd.args(["serve", "--port", "0", "--exit-with-parent"])
            .env("FOLIO_TOKEN", token)
            .env("FOLIO_PARENT_PID", std::process::id().to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            cmd.process_group(0);
        }
        let mut child = cmd.spawn().map_err(|e| format!("cannot launch core: {e}"))?;
        let stdout = child.stdout.take().ok_or("no stdout")?;
        {
            let (lock, _) = &*self.inner;
            let mut inner = lock.lock().unwrap();
            if inner.shutting_down {
                terminate_tree(&mut child);
                return Err("Folio was closed during startup".into());
            }
            inner.child = Some(child);
        }
        let mut lines = BufReader::new(stdout).lines();
        let port = loop {
            match lines.next() {
                Some(Ok(line)) => {
                    if let Some(json) = line.strip_prefix(READY_PREFIX) {
                        let v: serde_json::Value = serde_json::from_str(json).map_err(|e| e.to_string())?;
                        break v["port"].as_u64().ok_or("ready line without port")?;
                    }
                }
                _ => return Err("Core startup failed. See ~/.local/share/folio/logs/core.log for the cause.".into()),
            }
        };
        // Keep draining stdout so the core never blocks on a full pipe.
        thread::spawn(move || for _ in lines.by_ref() {});

        let (lock, cvar) = &*self.inner;
        let mut inner = lock.lock().unwrap();
        if inner.shutting_down { return Err("Folio was closed during startup".into()); }
        inner.connection = Some(Connection { base_url: format!("http://127.0.0.1:{port}"), token: token.into() });
        inner.error = None;
        cvar.notify_all();
        drop(inner);
        Ok(())
    }

    /// Wait (up to `timeout`) until the core is ready.
    pub fn connection(&self, timeout: Duration) -> Result<Connection, String> {
        let (lock, cvar) = &*self.inner;
        let guard = lock.lock().unwrap();
        let (guard, _) = cvar
            .wait_timeout_while(guard, timeout, |i| i.connection.is_none() && i.error.is_none())
            .unwrap();
        match (&guard.connection, &guard.error) {
            (Some(c), _) => Ok(c.clone()),
            (None, Some(e)) => Err(e.clone()),
            _ => Err("timed out waiting for the core service".into()),
        }
    }

    pub fn stop(&self) {
        let (lock, cvar) = &*self.inner;
        let mut inner = lock.lock().unwrap();
        inner.shutting_down = true;
        inner.connection = None;
        inner.error = Some("Folio was closed".into());
        if let Some(mut child) = inner.child.take() {
            terminate_tree(&mut child);
        }
        cvar.notify_all();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpStream;

    fn get(base: &str, path: &str, token: Option<&str>) -> String {
        let mut stream = TcpStream::connect(base.trim_start_matches("http://")).unwrap();
        let auth = token.map(|t| format!("Authorization: Bearer {t}\r\n")).unwrap_or_default();
        write!(stream, "GET {path} HTTP/1.0\r\nHost: localhost\r\n{auth}\r\n").unwrap();
        let mut out = String::new();
        stream.read_to_string(&mut out).unwrap();
        out
    }

    /// Launches the real core (this checkout's venv) and talks to it.
    /// Run with: `cargo test -- --ignored --test-threads=1` (needs `uv sync`).
    #[test]
    #[ignore = "starts the Python core; needs the venv"]
    fn starts_core_and_enforces_the_session_token() {
        let data = std::env::temp_dir().join(format!("folio-sidecar-test-{}", std::process::id()));
        std::env::set_var("FOLIO_DATA_DIR", &data);
        std::env::set_var("FOLIO_STT", "none");
        std::env::set_var("FOLIO_WATCH", "0");

        let sidecar = Sidecar::default();
        sidecar.start();
        let conn = sidecar.connection(Duration::from_secs(180)).expect("core became ready");
        assert!(conn.base_url.starts_with("http://127.0.0.1:"));
        assert_eq!(conn.token.len(), 64);

        assert!(get(&conn.base_url, "/api/health", None).contains("200 OK"));
        assert!(get(&conn.base_url, "/api/status", None).contains("401"));
        let status = get(&conn.base_url, "/api/status", Some(&conn.token));
        assert!(status.contains("200 OK") && status.contains("\"network_mode\":\"local\""));

        sidecar.stop();
        thread::sleep(Duration::from_millis(800));
        assert!(TcpStream::connect(conn.base_url.trim_start_matches("http://")).is_err(), "core stopped");
        let _ = std::fs::remove_dir_all(data);
    }

    #[cfg(unix)]
    #[test]
    #[ignore = "starts and terminates a delayed core subprocess"]
    fn stops_core_while_it_is_still_starting() {
        use std::os::unix::fs::PermissionsExt;
        let folder = std::env::temp_dir().join(format!("folio-startup-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&folder).unwrap();
        let script = folder.join("delayed-core");
        std::fs::write(&script, "#!/bin/sh\nsleep 20\n").unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o700)).unwrap();
        let old = std::env::var_os("FOLIO_CORE_CMD");
        std::env::set_var("FOLIO_CORE_CMD", &script);
        let sidecar = Sidecar::default();
        sidecar.start();
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        let pid = loop {
            let (lock, _) = &*sidecar.inner;
            if let Some(pid) = lock.lock().unwrap().child.as_ref().map(|child| child.id()) { break pid; }
            assert!(std::time::Instant::now() < deadline, "startup child was not registered");
            thread::sleep(Duration::from_millis(10));
        };
        sidecar.stop();
        if let Some(value) = old { std::env::set_var("FOLIO_CORE_CMD", value); }
        else { std::env::remove_var("FOLIO_CORE_CMD"); }
        assert_ne!(unsafe { libc::kill(pid as i32, 0) }, 0, "startup launcher survived shutdown");
        let _ = std::fs::remove_dir_all(folder);
    }
}
