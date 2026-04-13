import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { DsltransProvider, useDsltrans } from "@/contexts/DsltransContext";
import CanvasManager from "@/features/canvas/CanvasManager";
import DsltransRuleEditor from "@/features/dsltrans/DsltransRuleEditor";
import DsltransTextPanel from "@/features/dsltrans/DsltransTextPanel";
import TransformationPropertyPanel from "@/features/dsltrans/TransformationPropertyPanel";
import ModelPanel from "@/features/models/ModelPanel";
import MetamodelPanel from "@/features/models/MetamodelPanel";
import RunnerPanel from "@/features/runner/RunnerPanel";
import { autoLayoutNodes } from "@/features/layout/autoLayout";
import {
  parseXmiToGraph,
  stringifyGraphToXmi,
  validateInputModelForTransformation,
} from "@/utils/xmiUtils";

const defaultInputXmi = `<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="c1" xsi:type="Class:Class" />
</model>`;
const defaultOutputXmi = `<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>`;
const INPUT_STORAGE_KEY = "dsltrans-studio-input-xmi";
const OUTPUT_STORAGE_KEY = "dsltrans-studio-output-xmi";

function Workspace() {
  const {
    specText,
    setSpecTextAndSync,
    transformationSourceMetamodel,
    transformationTargetMetamodel,
    transformationSourceMetamodelDetail,
    transformationTargetMetamodelDetail,
    documentMode,
    fragmentStatus,
  } = useDsltrans();
  const storedInputText = typeof window === "undefined"
    ? defaultInputXmi
    : window.localStorage.getItem(INPUT_STORAGE_KEY) || defaultInputXmi;
  const storedOutputText = typeof window === "undefined"
    ? defaultOutputXmi
    : window.localStorage.getItem(OUTPUT_STORAGE_KEY) || defaultOutputXmi;
  const [inputText, setInputText] = useState(storedInputText);
  const [outputText, setOutputText] = useState(storedOutputText);

  const [inputGraph, setInputGraph] = useState(() => parseXmiToGraph(storedInputText));
  const [outputGraph, setOutputGraph] = useState(() => parseXmiToGraph(storedOutputText));
  const [builtInExamples, setBuiltInExamples] = useState([]);

  const [expandedPanel, setExpandedPanel] = useState(null);
  const [portalReady, setPortalReady] = useState(false);
  const portalContainerRef = useRef(null);

  const [panelWidths, setPanelWidths] = useState({ left: 25, center: 50, right: 25 });
  const workspaceRef = useRef(null);
  const dragRef = useRef(null);

  const MIN_PANEL_PCT = 15;
  const MAX_PANEL_PCT = 55;

  const handleLeftDividerMouseDown = (e) => {
    e.preventDefault();
    dragRef.current = { divider: "left", startX: e.clientX, startWidths: { ...panelWidths } };
  };
  const handleRightDividerMouseDown = (e) => {
    e.preventDefault();
    dragRef.current = { divider: "right", startX: e.clientX, startWidths: { ...panelWidths } };
  };

  useEffect(() => {
    const container = workspaceRef.current;
    const onMove = (e) => {
      if (!container || !dragRef.current) return;
      const dx = e.clientX - dragRef.current.startX;
      const deltaPct = (dx / container.offsetWidth) * 100;
      const { left, center, right } = dragRef.current.startWidths;
      if (dragRef.current.divider === "left") {
        const newLeft = Math.min(MAX_PANEL_PCT, Math.max(MIN_PANEL_PCT, left + deltaPct));
        const newCenter = center - (newLeft - left);
        if (newCenter >= MIN_PANEL_PCT) setPanelWidths({ left: newLeft, center: newCenter, right });
      } else {
        const newRight = Math.min(MAX_PANEL_PCT, Math.max(MIN_PANEL_PCT, right - deltaPct));
        const newCenter = center - (newRight - right);
        if (newCenter >= MIN_PANEL_PCT) setPanelWidths({ left, center: newCenter, right: newRight });
      }
    };
    const onUp = () => { dragRef.current = null; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(INPUT_STORAGE_KEY, inputText);
  }, [inputText]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(OUTPUT_STORAGE_KEY, outputText);
  }, [outputText]);

  useEffect(() => {
    let ignore = false;
    fetch("./example-library.json")
      .then((response) => response.json())
      .then((examples) => {
        if (!ignore) setBuiltInExamples(Array.isArray(examples) ? examples : []);
      })
      .catch(() => {
        if (!ignore) setBuiltInExamples([]);
      });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const el = document.createElement("div");
    el.id = "model-expand-portal";
    document.body.appendChild(el);
    portalContainerRef.current = el;
    setPortalReady(true);
    return () => {
      if (portalContainerRef.current?.parentNode) {
        portalContainerRef.current.parentNode.removeChild(portalContainerRef.current);
      }
      portalContainerRef.current = null;
      setPortalReady(false);
    };
  }, []);

  const handleLoadInputModel = async (fileText) => {
    const validation = validateInputModelForTransformation(fileText, transformationSourceMetamodel);
    if (!validation.ok) return validation;
    const parsed = parseXmiToGraph(fileText);
    setInputText(fileText);
    setInputGraph({ ...parsed, nodes: autoLayoutNodes(parsed.nodes, 520) });
    return { ok: true };
  };

  const handleLoadBuiltInExample = async (exampleId) => {
    const example = builtInExamples.find((entry) => entry.id === exampleId);
    if (!example) return;
    try {
      const specTextResponse = await fetch(`.${example.specPath}`);
      const nextSpecText = await specTextResponse.text();
      setSpecTextAndSync(nextSpecText);
      if (example.modelPath) {
        const modelTextResponse = await fetch(`.${example.modelPath}`);
        const modelText = await modelTextResponse.text();
        await handleLoadInputModel(modelText);
      }
    } catch (error) {
      console.error("Failed to load built-in example", error);
    }
  };

  const overlayStyles = {
    position: "fixed",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 99999,
    background: "#fff",
    overflow: "auto",
    padding: "1rem",
  };

  const expandedOverlay =
    portalReady && portalContainerRef.current && expandedPanel === "input"
      ? createPortal(
          <div
            className="overflow-auto p-4"
            style={overlayStyles}
            role="dialog"
            aria-modal="true"
            aria-label="Input Model (expanded)"
          >
            <div className="max-w-[1600px] mx-auto space-y-3">
              <ModelPanel
                title="Input Model"
                graph={inputGraph}
                text={inputText}
                setText={setInputText}
                setGraph={(next) => {
                  setInputGraph(next);
                  setInputText(stringifyGraphToXmi(next, "Model"));
                }}
                sourceMetamodel={transformationSourceMetamodel}
                canLoadModel={Boolean(transformationSourceMetamodel)}
                onLoadModel={handleLoadInputModel}
                isExpanded={true}
                onExpand={() => setExpandedPanel("input")}
                onCollapse={() => setExpandedPanel(null)}
                fullScreenMode
              />
            </div>
          </div>,
          portalContainerRef.current,
        )
      : portalReady && portalContainerRef.current && expandedPanel === "output"
        ? createPortal(
            <div
              className="overflow-auto p-4"
              style={overlayStyles}
              role="dialog"
              aria-modal="true"
              aria-label="Output Model (expanded)"
            >
              <div className="max-w-[1600px] mx-auto space-y-3">
                <ModelPanel
                  title="Output Model"
                  graph={outputGraph}
                  text={outputText}
                  setText={setOutputText}
                  setGraph={(next) => {
                    setOutputGraph(next);
                    setOutputText(stringifyGraphToXmi(next, "Model"));
                  }}
                  mermaidMetamodel={transformationTargetMetamodel}
                  isExpanded={true}
                  onExpand={() => setExpandedPanel("output")}
                  onCollapse={() => setExpandedPanel(null)}
                  fullScreenMode
                />
              </div>
            </div>,
            portalContainerRef.current,
          )
        : portalReady && portalContainerRef.current && expandedPanel === "source_metamodel"
          ? createPortal(
              <div
                className="overflow-auto p-4"
                style={overlayStyles}
                role="dialog"
                aria-modal="true"
                aria-label="Source Metamodel (expanded)"
              >
                <div className="max-w-[1600px] mx-auto space-y-3">
                  <MetamodelPanel
                    title="Source Metamodel"
                    metamodel={transformationSourceMetamodelDetail}
                    isExpanded={true}
                    onExpand={() => setExpandedPanel("source_metamodel")}
                    onCollapse={() => setExpandedPanel(null)}
                    fullScreenMode
                  />
                </div>
              </div>,
              portalContainerRef.current,
            )
          : portalReady && portalContainerRef.current && expandedPanel === "target_metamodel"
            ? createPortal(
                <div
                  className="overflow-auto p-4"
                  style={overlayStyles}
                  role="dialog"
                  aria-modal="true"
                  aria-label="Target Metamodel (expanded)"
                >
                  <div className="max-w-[1600px] mx-auto space-y-3">
                    <MetamodelPanel
                      title="Target Metamodel"
                      metamodel={transformationTargetMetamodelDetail}
                      isExpanded={true}
                      onExpand={() => setExpandedPanel("target_metamodel")}
                      onCollapse={() => setExpandedPanel(null)}
                      fullScreenMode
                    />
                  </div>
                </div>,
                portalContainerRef.current,
              )
            : portalReady && portalContainerRef.current && expandedPanel === "properties"
              ? createPortal(
                  <div
                    className="overflow-auto p-4"
                    style={overlayStyles}
                    role="dialog"
                    aria-modal="true"
                    aria-label="Transformation Properties (expanded)"
                  >
                    <div className="max-w-[900px] mx-auto space-y-3">
                      <TransformationPropertyPanel
                        isExpanded={true}
                        onExpand={() => setExpandedPanel("properties")}
                        onCollapse={() => setExpandedPanel(null)}
                        fullScreenMode
                      />
                    </div>
                  </div>,
                  portalContainerRef.current,
                )
              : null;

  return (
    <>
      {expandedOverlay}
      <div className="h-screen w-screen bg-slate-100 text-slate-900 p-3 overflow-hidden">
        <div
          ref={workspaceRef}
          className="flex h-full overflow-hidden"
          style={{ gap: 0 }}
        >
          <section
            className="overflow-auto space-y-3 flex-shrink-0"
            style={{
              width: `${panelWidths.left}%`,
              minWidth: `${MIN_PANEL_PCT}%`,
            }}
          >
            <DsltransRuleEditor />
            <RunnerPanel
              specText={specText}
              inputModelText={inputText}
              onOutputModelText={(xmi) => {
                const parsed = parseXmiToGraph(xmi);
                setOutputText(xmi);
                setOutputGraph({ ...parsed, nodes: autoLayoutNodes(parsed.nodes, 520) });
              }}
              documentMode={documentMode}
              fragmentStatus={fragmentStatus}
            />
          </section>
          <div
            role="separator"
            aria-label="Resize left panel"
            className="flex-shrink-0 flex justify-center self-stretch select-none cursor-col-resize bg-slate-400 hover:bg-slate-500 border border-slate-500"
            style={{ width: 10 }}
            onMouseDown={handleLeftDividerMouseDown}
            title="Drag to resize panels"
          >
            <div className="w-0.5 h-full flex flex-col justify-center gap-1 py-4 pointer-events-none">
              {[1, 2, 3].map((i) => (
                <div key={i} className="w-0.5 h-2 rounded-full bg-slate-500 opacity-70" />
              ))}
            </div>
          </div>
          <section
            className="overflow-auto min-h-0 flex-shrink-0"
            style={{
              width: `${panelWidths.center}%`,
              minWidth: `${MIN_PANEL_PCT}%`,
            }}
          >
            <CanvasManager />
          </section>
          <div
            role="separator"
            aria-label="Resize right panel"
            className="flex-shrink-0 flex justify-center self-stretch select-none cursor-col-resize bg-slate-400 hover:bg-slate-500 border border-slate-500"
            style={{ width: 10 }}
            onMouseDown={handleRightDividerMouseDown}
            title="Drag to resize panels"
          >
            <div className="w-0.5 h-full flex flex-col justify-center gap-1 py-4 pointer-events-none">
              {[1, 2, 3].map((i) => (
                <div key={i} className="w-0.5 h-2 rounded-full bg-slate-500 opacity-70" />
              ))}
            </div>
          </div>
          <section
            className="overflow-auto space-y-3 flex-shrink-0"
            style={{
              width: `${panelWidths.right}%`,
              minWidth: `${MIN_PANEL_PCT}%`,
            }}
          >
            <DsltransTextPanel builtInExamples={builtInExamples} onLoadBuiltInExample={handleLoadBuiltInExample} />
            <TransformationPropertyPanel
              isExpanded={expandedPanel === "properties"}
              onExpand={() => setExpandedPanel("properties")}
              onCollapse={() => setExpandedPanel(null)}
            />
            <MetamodelPanel
              title="Source Metamodel"
              metamodel={transformationSourceMetamodelDetail}
              isExpanded={expandedPanel === "source_metamodel"}
              onExpand={() => setExpandedPanel("source_metamodel")}
              onCollapse={() => setExpandedPanel(null)}
            />
            <MetamodelPanel
              title="Target Metamodel"
              metamodel={transformationTargetMetamodelDetail}
              isExpanded={expandedPanel === "target_metamodel"}
              onExpand={() => setExpandedPanel("target_metamodel")}
              onCollapse={() => setExpandedPanel(null)}
            />
            <ModelPanel
              title="Input Model"
              graph={inputGraph}
              text={inputText}
              setText={setInputText}
              setGraph={(next) => {
                setInputGraph(next);
                setInputText(stringifyGraphToXmi(next, "Model"));
              }}
              sourceMetamodel={transformationSourceMetamodel}
              canLoadModel={Boolean(transformationSourceMetamodel)}
              onLoadModel={handleLoadInputModel}
              builtInExamples={builtInExamples.filter((example) => example.modelPath)}
              onLoadBuiltInExample={handleLoadBuiltInExample}
              isExpanded={expandedPanel === "input"}
              onExpand={() => setExpandedPanel("input")}
              onCollapse={() => setExpandedPanel(null)}
            />
            <ModelPanel
              title="Output Model"
              graph={outputGraph}
              text={outputText}
              setText={setOutputText}
              setGraph={(next) => {
                setOutputGraph(next);
                setOutputText(stringifyGraphToXmi(next, "Model"));
              }}
              mermaidMetamodel={transformationTargetMetamodel}
              isExpanded={expandedPanel === "output"}
              onExpand={() => setExpandedPanel("output")}
              onCollapse={() => setExpandedPanel(null)}
            />
          </section>
        </div>
      </div>
    </>
  );
}

export default function App() {
  return (
    <DsltransProvider>
      <Workspace />
    </DsltransProvider>
  );
}
