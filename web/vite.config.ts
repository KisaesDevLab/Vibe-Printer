import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Built into the FastAPI static mount at /admin (P17.1 / P23.3).
export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  build: {
    outDir: "../app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/v1": "http://localhost:8080",
      "/healthz": "http://localhost:8080",
    },
  },
});
