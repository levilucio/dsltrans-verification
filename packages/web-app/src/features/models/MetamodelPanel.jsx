import MetamodelGraphView from "@/features/models/MetamodelGraphView";

export default function MetamodelPanel({
  title,
  metamodel,
  isExpanded = false,
  onExpand,
  onCollapse,
  fullScreenMode = false,
}) {
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
        </div>
      </div>
      {!metamodel ? (
        <div className="text-xs text-slate-500 border rounded p-3 bg-slate-50">
          Load a transformation (.dslt) to visualize source/target metamodels.
        </div>
      ) : (
        <>
          <div className="text-xs text-slate-600">Metamodel: <strong>{metamodel.name}</strong></div>
          <MetamodelGraphView
            metamodel={metamodel}
            width={fullScreenMode ? 1200 : 580}
            height={fullScreenMode ? 600 : 380}
            fullScreenMode={fullScreenMode}
          />
        </>
      )}
    </>
  );

  const wrapperClass = fullScreenMode ? "space-y-3" : "p-3 border rounded bg-white space-y-2";
  return <div className={wrapperClass}>{content}</div>;
}

