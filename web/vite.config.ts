import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  server: { proxy: { "/api": { target: "http://127.0.0.1:8000", ws: true } } },
  plugins: [react(), VitePWA({ registerType: "prompt", includeAssets: ["favicon.svg", "apple-touch-icon.png"],
    manifest: {
      name: "Rig operator console",
      short_name: "Rig Console",
      description: "Operator console for the pick-and-place gantry rig.",
      display: "standalone",
      orientation: "any",
      start_url: "/",
      background_color: "#0B0D0F",
      theme_color: "#0B0D0F",
      icons: [
        { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
        { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
        { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" }
      ]
    }, workbox: { globPatterns: ["**/*.{js,css,html,ico,png,svg,woff2}"] } })]
});
