import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  server: { proxy: { "/api": { target: "http://127.0.0.1:8000", ws: true } } },
  plugins: [react(), VitePWA({ registerType: "prompt", manifest: { name: "Rig operator console", short_name: "Rig Console", display: "standalone", start_url: "/", icons: [] }, workbox: { globPatterns: ["**/*.{js,css,html,ico,png,svg}"] } })]
});
