import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The dev server proxies to scripts/serve_local.py so the app talks to the
    // real Lambda handlers instead of a mock.
    proxy: {
      "/scan": "http://127.0.0.1:8000",
      "/shelf": "http://127.0.0.1:8000",
      "/alerts": "http://127.0.0.1:8000",
      "/search": "http://127.0.0.1:8000",
      "/stats": "http://127.0.0.1:8000",
      "/pharmacy": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
