import { useState } from "react";
import { runConcrete, runCutoff, runExplore, runSmtDirectStream } from "@/utils/apiClient";

const PROOF_MODES = ["explore", "smt_direct", "cutoff"];

export default function RunnerPanel({ specText, inputModelText, onOutputModelText, documentMode = "fragment", fragmentStatus }) {
  const [mode, setMode] = useState("concrete");
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(null);

  const proofDisabled = false;
  const nonFragmentAutoProofOnly = documentMode !== "fragment" || (fragmentStatus && fragmentStatus.loadable === false);

  const run = async () => {
    setWorking(true);
    setError("");
    setProgress(null);
    try {
      if (nonFragmentAutoProofOnly && (mode === "explore" || mode === "cutoff")) {
        throw new Error("Non-fragment specs support proof through SMT Direct (Hybrid) auto-abstraction only.");
      }
      let response;
      const payload = {
        specText,
        inputXmi: inputModelText,
      };
      if (mode === "concrete") response = await runConcrete(payload);
      if (mode === "explore") response = await runExplore(payload);
      if (mode === "smt_direct") {
        setResult({ mode: "hybrid", results: [], proofPreparation: null });
        response = await runSmtDirectStream({
          ...payload,
          dependencyMode: "trace_attr_aware",
          timeoutMs: 180000,
        }, (event) => {
          if (event.event === "start") {
            setProgress({
              total: event.total,
              completed: 0,
              remaining: event.total,
              lastProperty: null,
            });
            return;
          }
          if (event.event === "property_result") {
            setProgress({
              total: event.total,
              completed: event.completed,
              remaining: event.remaining,
              lastProperty: event.result?.property ?? null,
            });
            setResult((prev) => ({
              mode: event.mode,
              results: [...(prev?.results ?? []), event.result],
            }));
            return;
          }
          if (event.event === "complete") {
            setProgress({
              total: event.total,
              completed: event.completed,
              remaining: event.remaining,
              lastProperty: event.results?.[event.results.length - 1]?.property ?? null,
            });
          }
        });
      }
      if (mode === "cutoff") response = await runCutoff(payload);
      if (response?.outputXmi) onOutputModelText(response.outputXmi);
      setResult(response.event === "complete" ? { mode: response.mode, results: response.results } : response);
    } catch (err) {
      setError(err.message);
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="p-3 border rounded bg-white space-y-2">
      <h4 className="text-sm font-semibold">Runner</h4>
      <div className="text-xs text-slate-600">
        {documentMode === "fragment" && (fragmentStatus?.loadable !== false)
          ? "Fragment: concrete and proof modes available."
          : "Non-fragment: SMT Direct auto-derives finite proof abstraction from concrete spec."}
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <label className="flex items-center gap-2">
          <input type="radio" checked={mode === "concrete"} onChange={() => setMode("concrete")} />
          Concrete
        </label>
        <label
          className={`flex items-center gap-2 ${proofDisabled || nonFragmentAutoProofOnly ? "opacity-60" : ""}`}
          title={proofDisabled ? "Proof mode unavailable" : (nonFragmentAutoProofOnly ? "Use SMT Direct for non-fragment auto-abstraction" : "")}
        >
          <input type="radio" checked={mode === "explore"} onChange={() => setMode("explore")} disabled={proofDisabled || nonFragmentAutoProofOnly} />
          Symbolic Explore
        </label>
        <label className={`flex items-center gap-2 ${proofDisabled ? "opacity-60" : ""}`} title={proofDisabled ? "Proof mode unavailable" : ""}>
          <input type="radio" checked={mode === "smt_direct"} onChange={() => setMode("smt_direct")} disabled={proofDisabled} />
          SMT Direct (Hybrid)
        </label>
        <label
          className={`flex items-center gap-2 ${proofDisabled || nonFragmentAutoProofOnly ? "opacity-60" : ""}`}
          title={proofDisabled ? "Proof mode unavailable" : (nonFragmentAutoProofOnly ? "Use SMT Direct for non-fragment auto-abstraction" : "")}
        >
          <input type="radio" checked={mode === "cutoff"} onChange={() => setMode("cutoff")} disabled={proofDisabled || nonFragmentAutoProofOnly} />
          Cutoff
        </label>
      </div>
      <button className="px-3 py-1 border rounded text-xs" onClick={run} disabled={working}>
        {working ? "Running..." : "Run Transformation"}
      </button>
      {working && mode === "smt_direct" && progress && (
        <div className="text-xs text-slate-700 border rounded bg-slate-50 p-2">
          <div>
            Proved {progress.completed} / {progress.total} properties. {progress.remaining} remaining.
          </div>
          {progress.lastProperty && <div>Last completed: {progress.lastProperty}</div>}
        </div>
      )}
      {error && <div className="text-xs text-red-700">{error}</div>}
      {result && <pre className="text-[11px] bg-slate-900 text-slate-100 rounded p-2 overflow-auto max-h-48">{JSON.stringify(result, null, 2)}</pre>}
    </div>
  );
}
