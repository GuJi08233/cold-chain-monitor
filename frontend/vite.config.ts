import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function normalize(value: string | undefined, fallback: string): string {
  const text = (value || "").trim();
  if (!text) {
    return fallback;
  }
  if (text.length > 1 && text.endsWith("/")) {
    return text.slice(0, -1);
  }
  return text;
}

function isRelativeBaseUrl(url: string): boolean {
  return url.startsWith("/");
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  const apiBaseUrl = normalize(env.VITE_API_BASE_URL, "/api");
  const wsBaseUrl = normalize(env.VITE_WS_BASE_URL, "/ws");
  const backendOrigin = normalize(env.VITE_BACKEND_ORIGIN, "http://127.0.0.1:8000");
  const backendWsOrigin = normalize(
    env.VITE_BACKEND_WS_ORIGIN,
    backendOrigin.replace(/^http/i, "ws"),
  );

  const proxy: Record<string, { target: string; changeOrigin: boolean; ws?: boolean }> = {};
  if (isRelativeBaseUrl(apiBaseUrl)) {
    proxy[apiBaseUrl] = {
      target: backendOrigin,
      changeOrigin: true,
    };
  }
  if (isRelativeBaseUrl(wsBaseUrl)) {
    proxy[wsBaseUrl] = {
      target: backendWsOrigin,
      ws: true,
      changeOrigin: true,
    };
  }

  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy,
    },
    build: {
      chunkSizeWarningLimit: 700,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ["react", "react-dom", "react-router-dom"],
            charts: ["echarts"],
            map: ["leaflet"],
          },
        },
      },
    },
  };
});
