import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The FastAPI backend serves /api; in dev we proxy to it (including the
// session WebSocket). `npm run build` emits to dist/, which the backend
// serves statically in production. TILES_API_PROXY overrides the proxy
// target (the launcher sets it when the API runs on another port).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.TILES_API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/test/**", "src/**/*.test.{ts,tsx}", "src/main.tsx"],
      reporter: ["text-summary", "text", "html"],
      thresholds: { lines: 80, statements: 80, functions: 80, branches: 80 },
    },
  },
});
