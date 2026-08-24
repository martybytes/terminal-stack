import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: vite serves the SPA on 5173 and proxies /api, /healthz and the /ws
// socket to the local backend (npm run dev starts both). Prod: `vite build`
// emits to dist/web, which the backend serves itself — same-origin either way.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "dist/web",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:3114",
      "/healthz": "http://127.0.0.1:3114",
      "/ws": { target: "ws://127.0.0.1:3114", ws: true },
    },
  },
});
