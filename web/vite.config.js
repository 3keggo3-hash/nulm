import { defineConfig } from "vite";
import { copyFileSync, mkdirSync, existsSync, readdirSync, unlinkSync, rmdirSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const TARGET_DIR = resolve(__dirname, "../src/claude_bridge/web");

function syncAssets() {
  return {
    name: "sync-assets",
    closeBundle() {
      const distDir = resolve(__dirname, "dist");
      const targetAssetsDir = resolve(TARGET_DIR, "assets");

      if (!existsSync(distDir)) return;

      if (!existsSync(targetAssetsDir)) {
        mkdirSync(targetAssetsDir, { recursive: true });
      }

      const distAssets = resolve(distDir, "assets");
      if (existsSync(distAssets)) {
        for (const file of readdirSync(targetAssetsDir)) {
          if (file.endsWith(".css") || file.endsWith(".js")) {
            unlinkSync(resolve(targetAssetsDir, file));
          }
        }
        for (const file of readdirSync(distAssets)) {
          copyFileSync(resolve(distAssets, file), resolve(targetAssetsDir, file));
        }
      }

      const htmlSrc = resolve(distDir, "index.html");
      if (existsSync(htmlSrc)) {
        copyFileSync(htmlSrc, resolve(TARGET_DIR, "index.html"));
      }

      const pySrc = resolve(__dirname, "../src/claude_bridge/web/terminal.py");
      const pyDest = resolve(TARGET_DIR, "terminal.py");
      if (existsSync(pySrc) && !existsSync(pyDest)) {
        copyFileSync(pySrc, pyDest);
      }
    },
  };
}

export default defineConfig({
  root: ".",
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  plugins: [syncAssets()],
});