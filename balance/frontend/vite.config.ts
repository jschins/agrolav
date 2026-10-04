import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5174,
    proxy: {
      "/result/beheer_instudo/api": {
        target: "http://127.0.0.1:8500",
        changeOrigin: true,
      },
      "/result/beheer_sdog/api": {
        target: "http://127.0.0.1:8500",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:8500",
        changeOrigin: true,
        rewrite: (path) => "/result/beheer_sdog" + path,
      },
    },
  },
});
