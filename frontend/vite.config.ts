import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL("../", import.meta.url)), "");
  const backendPort = process.env.BACKEND_PORT || env.BACKEND_PORT || "8000";
  const frontendPort = process.env.FRONTEND_PORT || env.FRONTEND_PORT || "5173";
  return {
    plugins: [react()],
    server: {
      port: Number(frontendPort),
      strictPort: false,
      proxy: { "/api": `http://127.0.0.1:${backendPort}` },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      clearMocks: true,
    },
  };
});
