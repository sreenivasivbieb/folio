import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Port 1420 is what the Tauri shell loads in dev (see apps/desktop/src-tauri/tauri.conf.json).
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  clearScreen: false,
  server: { port: 1420, strictPort: true, host: "127.0.0.1" },
  build: { target: "es2022", sourcemap: true, chunkSizeWarningLimit: 2000 },
  test: { environment: "node" },
});
