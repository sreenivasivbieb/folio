#!/usr/bin/env node
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const children = new Set();
let stopping = false;
function start(command, args, options = {}) {
  const child = spawn(command, args, { cwd: root, stdio: "inherit", detached: process.platform !== "win32", ...options });
  children.add(child);
  child.on("error", (error) => { console.error(`Cannot start ${command}: ${error.message}`); shutdown(1); });
  child.on("exit", (code) => { children.delete(child); if (!stopping) shutdown(code ?? 1); });
  return child;
}
function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    try {
      if (process.platform !== "win32" && child.pid) process.kill(-child.pid, "SIGTERM");
      else child.kill("SIGTERM");
    } catch (error) { if (error.code !== "ESRCH") console.error(error.message); }
  }
  process.exitCode = code;
}
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => shutdown());
start("uv", ["run", "--project", "services/core", "folio-core", "serve", "--port", "8765"],
  { env: { ...process.env, FOLIO_TOKEN: "dev" } });
start(process.platform === "win32" ? "npm.cmd" : "npm", ["run", "dev:ui"]);
console.log("Folio: http://127.0.0.1:1420 — local storage; Ctrl+C stops the backend and interface.");
