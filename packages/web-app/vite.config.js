import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";
import fs from "fs";
import path from "path";
import { createRequire } from "module";

export default defineConfig({
  base: "./",
  plugins: [
    react(),
    {
      name: "z3-static-assets",
      configureServer(server) {
        const require = createRequire(import.meta.url);
        let z3DirCandidates = [];
        try {
          const z3PkgPath = require.resolve("z3-solver/package.json");
          const z3PkgDir = path.dirname(z3PkgPath);
          z3DirCandidates.push(path.join(z3PkgDir, "build"));
          z3DirCandidates.push(z3PkgDir);
        } catch (_) {}

        const pickZ3Dir = () => {
          for (const dir of z3DirCandidates) {
            try {
              if (fs.existsSync(path.join(dir, "z3-built.js"))) return dir;
            } catch (_) {}
          }
          return null;
        };
        const z3Dir = pickZ3Dir();

        server.middlewares.use((req, res, next) => {
          if (!req.url) return next();
          const map = {
            "/z3-built.js": "z3-built.js",
            "/z3-built.wasm": "z3-built.wasm",
          };
          if (map[req.url] && z3Dir) {
            const fp = path.join(z3Dir, map[req.url]);
            if (fs.existsSync(fp)) {
              res.setHeader(
                "Content-Type",
                req.url.endsWith(".wasm")
                  ? "application/wasm"
                  : "application/javascript",
              );
              fs.createReadStream(fp).pipe(res);
              return;
            }
          }
          next();
        });
      },
    },
  ],
  define: {
    global: "globalThis",
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
      "@components": resolve(__dirname, "src/components"),
    },
  },
  server: {
    host: true,
    port: 3000,
    open: false,
    proxy: {
      "/api": {
        target: "http://localhost:3100",
        changeOrigin: true,
      },
    },
  },
  worker: {
    format: "es",
  },
});
