import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROVER_ROOT = path.resolve(__dirname, "../../prover");
const PY_BRIDGE = path.resolve(__dirname, "scripts", "dsltrans_bridge.py");
const PYTHON_BIN = process.env.PYTHON_BIN || (process.platform === "win32" ? "py" : "python3");

function runBridge(command, payload, timeoutMs = 180000) {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_BIN, [PY_BRIDGE, "--command", command], {
      cwd: PROVER_ROOT,
      stdio: ["pipe", "pipe", "pipe"],
      env: {
        ...process.env,
        PYTHONPATH: path.resolve(PROVER_ROOT, "src"),
      },
    });

    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (data) => {
      stdout += data.toString();
    });
    proc.stderr.on("data", (data) => {
      stderr += data.toString();
    });
    proc.on("error", (error) => reject(error));
    proc.on("close", (code) => {
      if (code !== 0) {
        try {
          const errJson = JSON.parse(stdout.trim());
          if (errJson.error) {
            reject(new Error(errJson.error));
            return;
          }
        } catch (_) {}
        reject(new Error(stderr || stdout || `Python bridge failed (${code})`));
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch (_) {
        resolve({ raw: stdout, stderr });
      }
    });

    const timeout = setTimeout(() => {
      proc.kill("SIGTERM");
      reject(new Error("Python bridge timed out"));
    }, timeoutMs);
    proc.on("close", () => clearTimeout(timeout));

    proc.stdin.write(JSON.stringify(payload));
    proc.stdin.end();
  });
}

export function streamBridge(command, payload, { timeoutMs = 180000, onEvent, onError, onClose } = {}) {
  const proc = spawn(PYTHON_BIN, [PY_BRIDGE, "--command", command], {
    cwd: PROVER_ROOT,
    stdio: ["pipe", "pipe", "pipe"],
    env: {
      ...process.env,
      PYTHONPATH: path.resolve(PROVER_ROOT, "src"),
    },
  });

  let stdoutBuffer = "";
  let stderr = "";
  let sawEvent = false;
  let sawErrorEvent = false;

  const emitLines = (chunk) => {
    stdoutBuffer += chunk.toString();
    const lines = stdoutBuffer.split(/\r?\n/);
    stdoutBuffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const event = JSON.parse(trimmed);
        sawEvent = true;
        if (event?.event === "error") {
          sawErrorEvent = true;
        }
        onEvent?.(event);
      } catch {
        stderr += `${trimmed}\n`;
      }
    }
  };

  proc.stdout.on("data", emitLines);
  proc.stderr.on("data", (data) => {
    stderr += data.toString();
  });
  proc.on("error", (error) => onError?.(error));

  const timeout = setTimeout(() => {
    proc.kill("SIGTERM");
    onError?.(new Error("Python bridge timed out"));
  }, timeoutMs);

  proc.on("close", (code) => {
    clearTimeout(timeout);
    if (stdoutBuffer.trim()) {
      emitLines("\n");
    }
    if (code !== 0) {
      if (sawErrorEvent) {
        onClose?.();
        return;
      }
      if (!sawEvent) {
        try {
          const errJson = JSON.parse(stdoutBuffer.trim());
          if (errJson.error) {
            onError?.(new Error(errJson.error));
            return;
          }
        } catch (_) {}
      }
      onError?.(new Error(stderr || `Python bridge failed (${code})`));
      return;
    }
    onClose?.();
  });

  proc.stdin.write(JSON.stringify(payload));
  proc.stdin.end();
  return proc;
}

export function parseDsltransSpec(payload) {
  return runBridge("parse", payload);
}

export function runDsltransConcrete(payload) {
  return runBridge("concrete", payload);
}

export function runDsltransExplore(payload) {
  return runBridge("explore", payload);
}

export function runDsltransSmtDirect(payload) {
  return runBridge("smt_direct", payload, 900000);
}

export function streamDsltransSmtDirect(payload, handlers = {}) {
  return streamBridge("smt_direct_stream", payload, { timeoutMs: 900000, ...handlers });
}

export function runDsltransCutoff(payload) {
  return runBridge("cutoff", payload);
}

export function validateDsltransFragment(payload) {
  return runBridge("validate_fragment", payload);
}
