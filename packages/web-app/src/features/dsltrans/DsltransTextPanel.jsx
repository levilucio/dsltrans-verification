import { useEffect, useRef, useState } from "react";
import { useDsltrans } from "@/contexts/DsltransContext";
import { parseDsltrans } from "@/utils/dsltransSerializer";
import { validateFragment } from "@/utils/apiClient";

export default function DsltransTextPanel({ builtInExamples = [], onLoadBuiltInExample }) {
  const {
    specText,
    setSpecTextAndSync,
    setTransformationMetamodels,
    updateDocumentModeLocked,
    newFragmentDocument,
    newNonFragmentDocument,
    documentMode,
    fragmentStatus,
  } = useDsltrans();
  const [message, setMessage] = useState("");
  const [draftText, setDraftText] = useState(specText);
  const [validatingLoad, setValidatingLoad] = useState(false);
  const fileInputRef = useRef(null);

  const validateText = () => {
    try {
      const parsed = parseDsltrans(draftText);
      setMessage(`Parsed ${parsed.layers.length} layer(s), ${parsed.rules.length} rule(s).`);
    } catch (error) {
      setMessage(`Parse error: ${error.message}`);
    }
  };

  const applyTextToGraph = async () => {
    try {
      const parsed = parseDsltrans(draftText);
      if (documentMode === "fragment") {
        setMessage("Checking fragment...");
        const response = await validateFragment({ specText: draftText });
        if (!response.loadable && (response.violations?.length ?? 0) > 0) {
          setMessage(`Fragment mode: edit blocked. Spec would leave verifiable fragment: ${(response.violations ?? []).slice(0, 3).join("; ")}.`);
          return;
        }
      }
      setSpecTextAndSync(draftText);
      setMessage(`Parsed ${parsed.layers.length} layer(s), ${parsed.rules.length} rule(s).`);
    } catch (error) {
      setMessage(`Parse error: ${error.message}`);
    }
  };

  const onLoadFileClick = () => fileInputRef.current?.click();

  const onFileChosen = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".dslt")) {
      setMessage("Only .dslt files are supported.");
      return;
    }

    const fileText = await file.text();
    setValidatingLoad(true);
    try {
      const response = await validateFragment({ specText: fileText });
      setDraftText(fileText);
      setSpecTextAndSync(fileText);
      setTransformationMetamodels(
        response.sourceMetamodel ?? null,
        response.targetMetamodel ?? null,
        response.sourceMetamodelDetail ?? null,
        response.targetMetamodelDetail ?? null,
      );
      const mode = response.loadable ? "fragment" : "non-fragment";
      updateDocumentModeLocked(mode, { loadable: response.loadable, violations: response.violations ?? [] });
      if (!response.loadable && response.violations?.length) {
        setMessage(
          `Loaded ${file.name}. Opened as non-fragment (outside direct fragment). Proof modes will auto-derive a finite proof abstraction from this concrete spec.`,
        );
      } else {
        setMessage(
          `Loaded ${file.name}. Opened as fragment with ${response.transformationCount} transformation(s).`,
        );
      }
    } catch (error) {
      setMessage(`Load failed: ${error.message}`);
    } finally {
      setValidatingLoad(false);
      event.target.value = "";
    }
  };

  const onDraftChange = (nextText) => {
    setDraftText(nextText);
    try {
      setSpecTextAndSync(nextText);
      const parsed = parseDsltrans(nextText);
      setMessage(`Parsed ${parsed.layers.length} layer(s), ${parsed.rules.length} rule(s).`);
    } catch (_) {
      // Keep last valid graph when text is temporarily invalid while typing.
    }
  };

  useEffect(() => {
    setDraftText(specText);
  }, [specText]);

  return (
    <div className="p-3 border rounded bg-white min-h-[58vh] flex flex-col gap-2">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h4 className="text-sm font-semibold">DSLTrans Text View</h4>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-slate-500" title="Immutable per document">
            Mode: {documentMode === "fragment" ? "Fragment" : "Non-fragment"}
          </span>
          <button className="text-xs border rounded px-2 py-1" onClick={newFragmentDocument} title="New fragment transformation">
            New (fragment)
          </button>
          <button className="text-xs border rounded px-2 py-1" onClick={newNonFragmentDocument} title="New non-fragment transformation">
            New (non-fragment)
          </button>
          <button className="text-xs border rounded px-2 py-1" onClick={validateText}>
            Validate
          </button>
          <button className="text-xs border rounded px-2 py-1" onClick={applyTextToGraph}>
            Apply
          </button>
          <button className="text-xs border rounded px-2 py-1" onClick={onLoadFileClick} disabled={validatingLoad}>
            {validatingLoad ? "Checking..." : "Load .dslt"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".dslt,text/plain"
            className="hidden"
            onChange={onFileChosen}
          />
        </div>
      </div>
      <textarea
        className="w-full flex-1 min-h-[420px] font-mono text-xs border rounded p-2"
        value={draftText}
        onChange={(evt) => onDraftChange(evt.target.value)}
      />
      <div className="text-xs text-slate-600">
        {message ||
          (fragmentStatus?.violations?.length
            ? `Non-fragment: ${fragmentStatus.violations.slice(0, 2).join("; ")}. Proof modes use auto-abstraction.`
            : "Text and graph are synchronized. Load a .dslt to lock fragment or non-fragment mode.")}
      </div>
    </div>
  );
}
