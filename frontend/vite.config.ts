import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/",
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  preview: { port: 4173, host: "127.0.0.1" },
  build: { target: "es2022", chunkSizeWarningLimit: 900 },
  test: { include: ["tests/**/*.test.ts"], environment: "node" },
});
