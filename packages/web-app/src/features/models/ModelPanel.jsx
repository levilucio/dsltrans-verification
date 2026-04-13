import { useRef, useState } from "react";
import ModelGraphView from "@/features/models/ModelGraphView";
import { autoLayoutNodes } from "@/features/layout/autoLayout";
import { parseXmiToGraph, getMermaidForModel, stringifyGraphToXmi } from "@/utils/xmiUtils";

export default function ModelPanel({
  title,
  graph,
  setGraph,
  text,
  setText,
  sourceMetamodel,
  /** When set (e.g. transformation target for output panel), drives specialized Mermaid (Activity, UML, …). */
  mermaidMetamodel,
  canLoadModel = false,
  onLoadModel,
  builtInExamples = [],
  onLoadBuiltInExample,
  isExpanded = false,
  onExpand,
  onCollapse,
  fullScreenMode = false,
}) {
  const [error, setError] = useState("");
  const [loadMessage, setLoadMessage] = useState("");
  const [exportMessage, setExportMessage] = useState("");
  const fileInputRef = useRef(null);

  const fromText = () => {
    try {
      const parsed = parseXmiToGraph(text);
      setGraph({ ...parsed, nodes: autoLayoutNodes(parsed.nodes, 520) });
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };

  const toText = () => {
    setText(stringifyGraphToXmi(graph, "Model"));
    setError("");
  };

  const onLoadModelClick = () => fileInputRef.current?.click();

  const onFileChosen = async (event) => {
    const file = event.target.files?.[0];
    if (!file || !onLoadModel) return;
    setLoadMessage("");
    try {
      const fileText = await file.text();
      const result = await onLoadModel(fileText);
      if (result?.ok) {
        setLoadMessage(`Loaded ${file.name}.`);
        setError("");
      } else {
        setLoadMessage(result?.error || "Load failed.");
      }
    } catch (err) {
      setLoadMessage(err.message || "Load failed.");
    }
    event.target.value = "";
  };

  const copyMermaid = async () => {
    const mermaid = getMermaidForModel(graph, text, title, mermaidMetamodel ?? sourceMetamodel);
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(mermaid);
      } else {
        const textArea = document.createElement("textarea");
        textArea.value = mermaid;
        textArea.style.position = "fixed";
        textArea.style.opacity = "0";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
      }
      setExportMessage("Mermaid copied.");
    } catch (err) {
      setExportMessage(err?.message || "Could not copy Mermaid.");
    }
  };

  const content = (
    <>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h4 className="text-sm font-semibold">{title}</h4>
        <div className="flex flex-wrap gap-2 items-center">
          {onExpand && (
            <button
              type="button"
              className="text-xs px-2 py-1 border rounded"
              onClick={isExpanded ? onCollapse : onExpand}
              title={isExpanded ? "Collapse" : "Expand to full screen"}
            >
              {isExpanded ? "Collapse" : "Expand"}
            </button>
          )}
          {onLoadModel != null && (
            <>
              <button
                className="text-xs px-2 py-1 border rounded"
                onClick={onLoadModelClick}
                disabled={!canLoadModel}
                title={
                  canLoadModel
                    ? "Load an XMI model (metamodel must match the loaded transformation source)"
                    : "Load a transformation first (.dslt) to enable loading an input model"
                }
              >
                Load .xmi
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".xmi,.xml,text/xml"
                className="hidden"
                onChange={onFileChosen}
              />
            </>
          )}
          <button className="text-xs px-2 py-1 border rounded" onClick={fromText}>
            {"Text -> Graph"}
          </button>
          <button className="text-xs px-2 py-1 border rounded" onClick={toText}>
            {"Graph -> Text"}
          </button>
          <button className="text-xs px-2 py-1 border rounded" onClick={copyMermaid}>
            {"Copy Mermaid"}
          </button>
        </div>
      </div>
      <ModelGraphView
        graph={graph}
        width={fullScreenMode ? 1200 : 580}
        height={fullScreenMode ? 600 : 380}
        fullScreenMode={fullScreenMode}
      />
      <textarea
        className="w-full border rounded p-2 font-mono text-xs"
        style={{ minHeight: fullScreenMode ? 280 : 160 }}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {error && <div className="text-xs text-red-700">{error}</div>}
      {loadMessage && (
        <div className={`text-xs ${loadMessage.startsWith("Loaded") ? "text-green-700" : "text-red-700"}`}>
          {loadMessage}
        </div>
      )}
      {exportMessage && (
        <div className={`text-xs ${exportMessage.startsWith("Mermaid copied") ? "text-green-700" : "text-red-700"}`}>
          {exportMessage}
        </div>
      )}
    </>
  );

  const wrapperClass = fullScreenMode ? "space-y-3" : "p-3 border rounded bg-white space-y-2";
  return <div className={wrapperClass}>{content}</div>;
}
