import { NODE_KINDS } from "@/utils/dsltransModel";
import { useDsltrans } from "@/contexts/DsltransContext";

export default function DsltransRuleEditor() {
  const {
    layers,
    nodes,
    selectedNodeId,
    updateNodeLabel,
    updateElementNode,
    addLayer,
    addRule,
    addRuleElement,
    deleteSelected,
    snapToGridEnabled,
    setSnapToGridEnabled,
    autoLayout,
    undo,
    redo,
    canUndo,
    canRedo,
    documentMode,
  } = useDsltrans();

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) || null;
  const ruleNodes = nodes.filter((n) => n.kind === NODE_KINDS.RULE);
  const isMatch = selectedNode?.kind === NODE_KINDS.MATCH;
  const isApply = selectedNode?.kind === NODE_KINDS.APPLY;
  const hasStruct = isMatch || isApply;

  return (
    <div className="flex flex-col gap-3">
      <div className="p-3 border rounded bg-white">
        <h3 className="font-semibold text-sm mb-2">DSLTrans Editor</h3>
        {documentMode === "fragment" && (
          <p className="text-xs text-slate-500 mb-2">Fragment mode: use Apply in Text View to confirm spec stays in fragment after edits.</p>
        )}
        <div className="flex flex-wrap gap-2">
          <button className="px-2 py-1 border rounded text-xs" onClick={addLayer}>
            Add Layer
          </button>
          <button
            className="px-2 py-1 border rounded text-xs"
            onClick={() => layers[0] && addRule(layers[0].id)}
            disabled={layers.length === 0}
          >
            Add Rule (Layer 1)
          </button>
          <button className="px-2 py-1 border rounded text-xs" onClick={autoLayout}>
            Auto Layout
          </button>
          <button className="px-2 py-1 border rounded text-xs" onClick={undo} disabled={!canUndo}>
            Undo
          </button>
          <button className="px-2 py-1 border rounded text-xs" onClick={redo} disabled={!canRedo}>
            Redo
          </button>
          <button
            className="px-2 py-1 border rounded text-xs"
            onClick={() => setSnapToGridEnabled((v) => !v)}
          >
            Snap: {snapToGridEnabled ? "On" : "Off"}
          </button>
        </div>
      </div>

      <div className="p-3 border rounded bg-white">
        <h4 className="font-semibold text-sm mb-2">Rules and Layers</h4>
        {layers.map((layer) => (
          <div key={layer.id} className="mb-2">
            <div className="text-xs font-medium mb-1">{layer.name}</div>
            <div className="space-y-1">
              {ruleNodes
                .filter((rule) => rule.layerId === layer.id)
                .map((rule) => (
                  <div key={rule.id} className="flex items-center gap-2">
                    <span className="text-xs text-slate-600">{rule.label}</span>
                    <button
                      className="px-1 py-0.5 text-xs border rounded"
                      onClick={() => addRuleElement(rule.id, NODE_KINDS.MATCH)}
                    >
                      + Match
                    </button>
                    <button
                      className="px-1 py-0.5 text-xs border rounded"
                      onClick={() => addRuleElement(rule.id, NODE_KINDS.APPLY)}
                    >
                      + Apply
                    </button>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>

      <div className="p-3 border rounded bg-white">
        <h4 className="font-semibold text-sm mb-2">Selection</h4>
        {!selectedNode ? (
          <div className="text-xs text-slate-500">Select a node in canvas.</div>
        ) : hasStruct ? (
          <div className="space-y-2">
            <div className="text-xs text-slate-600">Type: {selectedNode.kind}</div>
            <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 items-center text-xs">
              {isMatch && (
                <>
                  <label className="text-slate-600">Quantifier</label>
                  <select
                    className="border rounded px-2 py-1"
                    value={selectedNode.matchType ?? "any"}
                    onChange={(e) =>
                      updateElementNode(selectedNode.id, { matchType: e.target.value })
                    }
                  >
                    <option value="any">any</option>
                    <option value="exists">exists</option>
                  </select>
                </>
              )}
              <label className="text-slate-600">Variable</label>
              <input
                className="border rounded px-2 py-1 font-mono"
                value={selectedNode.varName ?? ""}
                onChange={(e) =>
                  updateElementNode(selectedNode.id, { varName: e.target.value.trim() })
                }
                placeholder="varName"
              />
              <label className="text-slate-600">Type</label>
              <input
                className="border rounded px-2 py-1 font-mono"
                value={selectedNode.className ?? ""}
                onChange={(e) =>
                  updateElementNode(selectedNode.id, { className: e.target.value.trim() })
                }
                placeholder="ClassName"
              />
              {isMatch && (
                <>
                  <label className="text-slate-600">where</label>
                  <input
                    className="border rounded px-2 py-1 font-mono"
                    value={selectedNode.whereClause ?? ""}
                    onChange={(e) =>
                      updateElementNode(selectedNode.id, { whereClause: e.target.value.trim() || null })
                    }
                    placeholder="expr (e.g. cls.isAbstract == true)"
                  />
                </>
              )}
            </div>
            {isApply && (
              <div className="space-y-1">
                <div className="text-xs font-medium text-slate-600">Attribute bindings</div>
                {(selectedNode.attributeBindings ?? []).map((b, i) => (
                  <div key={i} className="flex gap-1 items-center">
                    <input
                      className="flex-1 border rounded px-2 py-1 font-mono text-xs"
                      value={b.attr}
                      onChange={(e) => {
                        const next = [...(selectedNode.attributeBindings || [])];
                        next[i] = { ...b, attr: e.target.value };
                        updateElementNode(selectedNode.id, { attributeBindings: next });
                      }}
                      placeholder="attr"
                    />
                    <span className="text-slate-400">=</span>
                    <input
                      className="flex-1 border rounded px-2 py-1 font-mono text-xs"
                      value={b.expr}
                      onChange={(e) => {
                        const next = [...(selectedNode.attributeBindings || [])];
                        next[i] = { ...b, expr: e.target.value };
                        updateElementNode(selectedNode.id, { attributeBindings: next });
                      }}
                      placeholder="expr"
                    />
                    <button
                      type="button"
                      className="px-1 py-0.5 text-xs border rounded text-red-600"
                      onClick={() => {
                        const next = (selectedNode.attributeBindings ?? []).filter(
                          (_, j) => j !== i
                        );
                        updateElementNode(selectedNode.id, { attributeBindings: next });
                      }}
                    >
                      −
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="px-2 py-1 text-xs border rounded border-dashed"
                  onClick={() =>
                    updateElementNode(selectedNode.id, {
                      attributeBindings: [
                        ...(selectedNode.attributeBindings ?? []),
                        { attr: "attr", expr: "value" },
                      ],
                    })
                  }
                >
                  + Add binding
                </button>
              </div>
            )}
            <button className="px-2 py-1 text-xs border rounded text-red-700" onClick={deleteSelected}>
              Delete Selected
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="text-xs text-slate-600">Type: {selectedNode.kind}</div>
            <input
              className="w-full text-sm border rounded px-2 py-1"
              value={selectedNode.label}
              onChange={(evt) => updateNodeLabel(selectedNode.id, evt.target.value)}
            />
            <button className="px-2 py-1 text-xs border rounded text-red-700" onClick={deleteSelected}>
              Delete Selected
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
