import express from "express";
import cors from "cors";
import path from "path";
import { fileURLToPath } from "url";
import {
  parseDsltransSpec,
  runDsltransConcrete,
  runDsltransCutoff,
  runDsltransExplore,
  runDsltransSmtDirect,
  streamDsltransSmtDirect,
  validateDsltransFragment,
} from "./dsltransBridge.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DIST_DIR = path.resolve(__dirname, "../dist");

const app = express();
app.use(cors());
app.use(express.json({ limit: "10mb" }));
app.use(express.static(DIST_DIR));

app.get("/api/health", (_, res) => {
  res.json({ ok: true });
});

app.post("/api/dsltrans/parse", async (req, res) => {
  try {
    const data = await parseDsltransSpec(req.body);
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post("/api/dsltrans/run/concrete", async (req, res) => {
  try {
    const data = await runDsltransConcrete(req.body);
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post("/api/dsltrans/run/explore", async (req, res) => {
  try {
    const data = await runDsltransExplore(req.body);
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post("/api/dsltrans/run/smt_direct", async (req, res) => {
  try {
    const data = await runDsltransSmtDirect(req.body);
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post("/api/dsltrans/run/smt_direct_stream", (req, res) => {
  let closed = false;
  res.setHeader("Content-Type", "application/x-ndjson; charset=utf-8");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");

  const endOnce = () => {
    if (closed) return;
    closed = true;
    res.end();
  };

  streamDsltransSmtDirect(req.body, {
    onEvent(event) {
      res.write(`${JSON.stringify(event)}\n`);
    },
    onError(error) {
      const payload = { event: "error", error: error.message };
      if (!res.headersSent) {
        res.status(500);
      }
      res.write(`${JSON.stringify(payload)}\n`);
      endOnce();
    },
    onClose() {
      endOnce();
    },
  });
});

app.post("/api/dsltrans/run/cutoff", async (req, res) => {
  try {
    const data = await runDsltransCutoff(req.body);
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post("/api/dsltrans/validate_fragment", async (req, res) => {
  try {
    const data = await validateDsltransFragment(req.body);
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get("/*rest", (req, res, next) => {
  if (req.path.startsWith("/api/")) return next();
  res.sendFile(path.join(DIST_DIR, "index.html"));
});

const port = Number(process.env.PORT || 3100);
app.listen(port, () => {
  console.log(`DSLTrans bridge server running on http://localhost:${port}`);
});
