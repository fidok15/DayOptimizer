import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Build lands inside the Python package so `dayoptimizer web` needs no Node.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../src/dayoptimizer/web_static", emptyOutDir: true },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        // the API rejects foreign Origins; present the dev proxy as same-origin
        headers: { origin: "http://127.0.0.1:8765" },
      },
    },
  },
});
