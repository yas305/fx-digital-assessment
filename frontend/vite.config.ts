import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxying /api to the Python backend means the browser sees same-origin
    // requests in development, so there is no CORS preflight to think about.
    // The backend also sets permissive CORS headers for the dev ports, so the
    // app still works if it is ever run without this proxy.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
