import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The backend runs separately on :8000. Proxying /api in dev keeps the
// frontend talking to relative URLs, which is what a future mobile client
// would do against a deployed instance too.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
