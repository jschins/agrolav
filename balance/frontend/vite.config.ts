import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5174,
    proxy: {
      "/balance/beheer_instudo/api": {
        target: "http://127.0.0.1:8100",
        changeOrigin: true,
      },
      "/balance/beheer/api": {
        target: "http://127.0.0.1:8100",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:8100",
        changeOrigin: true,
        rewrite: (path) => "/balance/beheer" + path,
      },
    },
  },
});
