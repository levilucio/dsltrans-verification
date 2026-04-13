import { useMemo } from "react";
import { useDsltrans } from "@/contexts/DsltransContext";
import { parsePropertiesFromSpec, parsePropertyToGraph } from "@/utils/dsltransSerializer";
import PropertyGraphView from "@/features/dsltrans/PropertyGraphView";

export default function TransformationPropertyPanel({
  isExpanded = false,
  onExpand,
  onCollapse,
  fullScreenMode = false,
}) {
  const { specText } = useDsltrans();
  const properties = useMemo(
    () => (specText ? parsePropertiesFromSpec(specText) : []),
    [specText],
  );

  const content = (
    <>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h4 className="text-sm font-semibold">Transformation Properties</h4>
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
        </div>
      </div>
      {properties.length === 0 ? (
        <div className="text-xs text-slate-500 border rounded p-3 bg-slate-50">
          No <code>property Name "Optional description" &#123; precondition &#123; ... &#125; postcondition &#123; ... &#125; &#125;</code> blocks found in the transformation.
        </div>
      ) : (
        <ul className="space-y-2 list-none pl-0">
          {properties.map((p) => {
            const graph = parsePropertyToGraph(p.precondition, p.postcondition);
            const hasGraph = graph.preNodes.length > 0 || graph.postNodes.length > 0;
            return (
              <li key={p.name} className="border rounded bg-slate-50/50 p-2 text-xs">
                <div className="font-semibold text-slate-800 mb-1">{p.name}</div>
                {p.description && (
                  <div className="mb-2 text-slate-600 italic">{p.description}</div>
                )}
                {hasGraph && (
                  <div className="mb-2 rounded overflow-hidden border border-slate-200 bg-white inline-block">
                    <PropertyGraphView
                      preNodes={graph.preNodes}
                      postNodes={graph.postNodes}
                      preRelations={graph.preRelations}
                      postRelations={graph.postRelations}
                      traceEdges={graph.traceEdges}
                      width={320}
                    />
                  </div>
                )}
                <div className="grid grid-cols-[auto_1fr_auto_1fr] gap-x-2 gap-y-0.5 items-baseline">
                  <span className="text-slate-500">pre:</span>
                  <pre className="m-0 font-mono text-[11px] whitespace-pre-wrap break-words text-slate-700">
                    {p.precondition || "—"}
                  </pre>
                  <span className="text-slate-500">post:</span>
                  <pre className="m-0 font-mono text-[11px] whitespace-pre-wrap break-words text-slate-700">
                    {p.postcondition || "—"}
                  </pre>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );

  const wrapperClass = fullScreenMode ? "space-y-3" : "p-3 border rounded bg-white space-y-2";
  return <div className={wrapperClass}>{content}</div>;
}
