import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { createReadStream, existsSync, statSync } from "node:fs";
import { resolve, normalize, extname, sep } from "node:path";

// Mock mode (`?mock=1`) reads the real `polytale/content/` tree at `/mock-content/...`
// (language, personas, journey, scene JSON and art), so the in-browser mock plays the
// authored scenes with whatever art exists right now. Anything missing 404s and the
// mock falls back to its built-in script and neutral placeholder cutouts.
const CONTENT_DIR = resolve(__dirname, "..", "content");
const TYPES: Record<string, string> = {
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
};

function mockContent(): Plugin {
  return {
    name: "polytale-mock-content",
    configureServer(server) {
      server.middlewares.use("/mock-content", (req, res) => {
        const rel = decodeURIComponent((req.url || "/").split("?")[0]).replace(/^\/+/, "");
        const file = normalize(resolve(CONTENT_DIR, rel));
        const type = TYPES[extname(file).toLowerCase()];
        if (!type || !file.startsWith(CONTENT_DIR + sep) || !existsSync(file) || !statSync(file).isFile()) {
          res.statusCode = 404;
          res.setHeader("Content-Type", "text/plain");
          res.end("not found");
          return;
        }
        res.setHeader("Content-Type", type);
        res.setHeader("Cache-Control", "no-cache");
        if (req.method === "HEAD") {
          res.end();
          return;
        }
        createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), mockContent()],
  server: {
    port: Number(process.env.POLYTALE_WEB_PORT || 5180),
    strictPort: true,
    host: true,
    watch: {
      // WSL2 on /mnt/c: native file events don't cross the boundary, so poll.
      usePolling: true,
      interval: 500,
    },
    proxy: {
      "/api": `http://localhost:${process.env.POLYTALE_API_PORT || 8100}`,
    },
  },
});
