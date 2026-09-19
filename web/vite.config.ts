import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { createReadStream, existsSync, statSync } from "node:fs";
import { resolve, normalize, extname, sep } from "node:path";

// Mock mode (`?mock=1`) serves the cartridge's real art straight from
// `polytale/cartridges/<id>/art/` at `/mock-art/<file>`, so the in-browser mock
// API uses whatever art exists right now (another agent generates it) and the
// client falls back to painted placeholders for anything still missing.
const CART_DIR = resolve(__dirname, "..", "cartridges", "broken-airship-ja");
const ART_DIR = resolve(CART_DIR, "art");
const TYPES: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
};

function mockArt(): Plugin {
  return {
    name: "polytale-mock-art",
    configureServer(server) {
      // The authored cartridge, so the mock mirrors its objectives, help ladders and stage layout.
      server.middlewares.use("/mock-cartridge.json", (_req, res) => {
        const file = resolve(CART_DIR, "cartridge.json");
        if (!existsSync(file)) {
          res.statusCode = 404;
          res.end("{}");
          return;
        }
        res.setHeader("Content-Type", "application/json");
        res.setHeader("Cache-Control", "no-cache");
        createReadStream(file).pipe(res);
      });
      server.middlewares.use("/mock-art", (req, res, next) => {
        const rel = decodeURIComponent((req.url || "/").split("?")[0]).replace(/^\/+/, "");
        const file = normalize(resolve(ART_DIR, rel));
        if (!file.startsWith(ART_DIR + sep) || !existsSync(file) || !statSync(file).isFile()) {
          res.statusCode = 404;
          res.end("not found");
          return;
        }
        res.setHeader("Content-Type", TYPES[extname(file).toLowerCase()] || "application/octet-stream");
        res.setHeader("Cache-Control", "no-cache");
        createReadStream(file).pipe(res);
        void next;
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), mockArt()],
  server: {
    port: Number(process.env.POLYTALE_WEB_PORT || 5180),
    strictPort: true,
    host: true,
    watch: {
      // WSL2 on /mnt/c: native file events don't cross the boundary — poll instead.
      usePolling: true,
      interval: 500,
    },
    proxy: {
      "/api": `http://localhost:${process.env.POLYTALE_API_PORT || 8100}`,
    },
  },
});
