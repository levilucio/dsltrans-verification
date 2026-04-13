import { useCallback, useEffect, useMemo, useState } from "react";
import { Arrow, Group, Layer, Line, Rect, Stage, Text } from "react-konva";
import { buildMetamodelGraph } from "@/features/layout/metamodelLayout";

const DEFAULT_WIDTH = 580;
const DEFAULT_HEIGHT = 380;
const CONTENT_PADDING = 90;
const ASSOC_LABEL_FONT_SIZE = 10;
const MULT_LABEL_FONT_SIZE = 9;
const MULT_LABEL_WIDTH = 64;
const MULT_OFFSET = 14;

function multToText(mult) {
  if (!Array.isArray(mult) || mult.length < 2) return "";
  const [lo, hi] = mult;
  return `${lo ?? 0}..${hi == null ? "*" : hi}`;
}

function getBounds(nodes) {
  if (!nodes.length) return { width: 0, height: 0 };
  const minX = Math.min(...nodes.map((n) => n.x));
  const minY = Math.min(...nodes.map((n) => n.y));
  const maxX = Math.max(...nodes.map((n) => n.x + n.width));
  const maxY = Math.max(...nodes.map((n) => n.y + n.height));
  return {
    width: maxX - minX + CONTENT_PADDING,
    height: maxY - minY + CONTENT_PADDING,
  };
}

/** Endpoints for association/reference: exit source side, enter target side. Simple left/right so lines always connect. */
function edgeEndpoints(src, tgt, sourceRank = 0, sourceCount = 1, targetRank = 0, targetCount = 1) {
  const srcCx = src.x + src.width / 2;
  const tgtCx = tgt.x + tgt.width / 2;
  const leftToRight = srcCx <= tgtCx;
  const srcOffset = sourceCount > 1 ? (sourceRank - (sourceCount - 1) / 2) * 10 : 0;
  const tgtOffset = targetCount > 1 ? (targetRank - (targetCount - 1) / 2) * 10 : 0;
  const srcCy = src.y + src.height / 2;
  const tgtCy = tgt.y + tgt.height / 2;
  return {
    sx: src.x + (leftToRight ? src.width : 0),
    sy: srcCy + srcOffset,
    tx: tgt.x + (leftToRight ? 0 : tgt.width),
    ty: tgtCy + tgtOffset,
    sourceFace: leftToRight ? "right" : "left",
    targetFace: leftToRight ? "left" : "right",
  };
}

/** Inheritance: child (below) -> parent (above). Child top-center to parent bottom-center. */
function inheritanceEndpoints(childNode, parentNode) {
  return {
    sx: childNode.x + childNode.width / 2,
    sy: childNode.y,
    tx: parentNode.x + parentNode.width / 2,
    ty: parentNode.y + parentNode.height,
  };
}

/** Orthogonal path: horizontal – vertical – horizontal (4 points, 3 segments). Always connects (sx,sy) to (tx,ty). */
function orthogonalPath(sx, sy, tx, ty, edgeIndex = 0, edgeCount = 1) {
  const stagger = edgeCount > 1 ? (edgeIndex - (edgeCount - 1) / 2) * 18 : 0;
  const midX = (sx + tx) / 2 + stagger;
  return [sx, sy, midX, sy, midX, ty, tx, ty];
}

function multiplicityLabelPos(x, y, face) {
  if (face === "left") return { x: x - MULT_LABEL_WIDTH - MULT_OFFSET, y: y - 9 };
  if (face === "right") return { x: x + MULT_OFFSET, y: y - 9 };
  if (face === "top") return { x: x - MULT_LABEL_WIDTH / 2, y: y - 18 };
  return { x: x - MULT_LABEL_WIDTH / 2, y: y + 6 };
}

function diamondPoints(sx, sy, tx, ty, size = 7) {
  const dx = tx - sx;
  const dy = ty - sy;
  const len = Math.max(1, Math.hypot(dx, dy));
  const ux = dx / len;
  const uy = dy / len;
  const px = -uy;
  const py = ux;
  const c1x = sx + ux * size * 1.5;
  const c1y = sy + uy * size * 1.5;
  return [
    sx, sy,
    c1x + px * size, c1y + py * size,
    sx + ux * size * 3, sy + uy * size * 3,
    c1x - px * size, c1y - py * size,
  ];
}

export default function MetamodelGraphView({
  metamodel,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  fullScreenMode = false,
}) {
  const [zoom, setZoom] = useState(1);
  const [nodePositions, setNodePositions] = useState({});
  const graph = useMemo(() => buildMetamodelGraph(metamodel), [metamodel]);
  useEffect(() => setNodePositions({}), [metamodel]);
  const displayNodes = useMemo(
    () =>
      graph.nodes.map((n) => ({
        ...n,
        x: nodePositions[n.id]?.x ?? n.x,
        y: nodePositions[n.id]?.y ?? n.y,
      })),
    [graph.nodes, nodePositions],
  );
  const nodeMap = useMemo(() => new Map(displayNodes.map((n) => [n.id, n])), [displayNodes]);
  const outgoing = useMemo(() => {
    const m = new Map();
    graph.edges.forEach((e) => {
      if (e.edgeType === "inheritance") return;
      if (!m.has(e.sourceId)) m.set(e.sourceId, []);
      m.get(e.sourceId).push(e.id);
    });
    return m;
  }, [graph.edges]);
  const incoming = useMemo(() => {
    const m = new Map();
    graph.edges.forEach((e) => {
      if (e.edgeType === "inheritance") return;
      if (!m.has(e.targetId)) m.set(e.targetId, []);
      m.get(e.targetId).push(e.id);
    });
    return m;
  }, [graph.edges]);

  /** For association/composition: index of this edge among edges between same (sourceId, targetId). */
  const edgePairIndex = useMemo(() => {
    const pairToIds = new Map();
    graph.edges.forEach((e) => {
      if (e.edgeType === "inheritance") return;
      const key = `${e.sourceId}\t${e.targetId}`;
      if (!pairToIds.has(key)) pairToIds.set(key, []);
      pairToIds.get(key).push(e.id);
    });
    const out = new Map();
    pairToIds.forEach((ids) => {
      ids.forEach((id, i) => out.set(id, { index: i, count: ids.length }));
    });
    return out;
  }, [graph.edges]);

  const bounds = useMemo(() => getBounds(displayNodes), [displayNodes]);
  const handleNodeDragEnd = useCallback((nodeId) => (e) => {
    setNodePositions((prev) => ({
      ...prev,
      [nodeId]: { x: e.target.x(), y: e.target.y() },
    }));
  }, []);
  const stageWidth = Math.max(width, bounds.width);
  const stageHeight = Math.max(height, bounds.height);
  const scaledWidth = stageWidth * zoom;
  const scaledHeight = stageHeight * zoom;

  const scrollContainerStyle = fullScreenMode
    ? { maxHeight: "75vh", maxWidth: "92vw", minHeight: 300 }
    : undefined;

  return (
    <div className="border rounded bg-white flex flex-col">
      <div className="flex items-center gap-2 px-2 py-1 border-b bg-slate-50 text-xs">
        <button
          type="button"
          className="px-2 py-1 border rounded hover:bg-slate-200"
          onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))}
          aria-label="Zoom out"
        >
          −
        </button>
        <span className="min-w-[4rem]">Zoom {Math.round(zoom * 100)}%</span>
        <button
          type="button"
          className="px-2 py-1 border rounded hover:bg-slate-200"
          onClick={() => setZoom((z) => Math.min(2.5, z + 0.25))}
          aria-label="Zoom in"
        >
          +
        </button>
      </div>
      <div className="overflow-auto min-h-0 flex-1 min-h-[200px]" style={scrollContainerStyle}>
        <div style={{ width: scaledWidth, height: scaledHeight, minWidth: scaledWidth, minHeight: scaledHeight }}>
          <Stage width={scaledWidth} height={scaledHeight} scaleX={zoom} scaleY={zoom}>
            <Layer>
              {graph.edges.map((edge) => {
                const src = nodeMap.get(edge.sourceId);
                const tgt = nodeMap.get(edge.targetId);
                if (!src || !tgt) return null;

                if (edge.edgeType === "inheritance") {
                  const { sx, sy, tx, ty } = inheritanceEndpoints(src, tgt);
                  return (
                    <Group key={edge.id}>
                      <Arrow
                        points={[sx, sy, tx, ty]}
                        stroke="#2563eb"
                        fill="#ffffff"
                        strokeWidth={1.6}
                        pointerLength={11}
                        pointerWidth={11}
                      />
                    </Group>
                  );
                }

                const out = outgoing.get(edge.sourceId) || [];
                const inn = incoming.get(edge.targetId) || [];
                const endpointInfo = edgeEndpoints(
                  src,
                  tgt,
                  Math.max(out.indexOf(edge.id), 0),
                  out.length || 1,
                  Math.max(inn.indexOf(edge.id), 0),
                  inn.length || 1,
                );
                const { sx, sy, tx, ty, sourceFace, targetFace } = endpointInfo;
                const pairInfo = edgePairIndex.get(edge.id) ?? { index: 0, count: 1 };
                const pathPoints = orthogonalPath(sx, sy, tx, ty, pairInfo.index, pairInfo.count);
                const midX = pathPoints[2];
                const midY = (pathPoints[3] + pathPoints[5]) / 2;
                const sourceMultPos = multiplicityLabelPos(sx, sy, sourceFace);
                const targetMultPos = multiplicityLabelPos(tx, ty, targetFace);

                if (edge.edgeType === "composition") {
                  const dPoints = diamondPoints(sx, sy, pathPoints[2], pathPoints[3], 7);
                  return (
                    <Group key={edge.id}>
                      <Line points={pathPoints} stroke="#1f2937" strokeWidth={1.5} lineCap="round" lineJoin="round" />
                      <Line points={dPoints} closed fill="#1f2937" stroke="#1f2937" strokeWidth={1} />
                      <Text x={midX - 60} y={midY - 19} width={120} text={edge.label || ""} fontSize={ASSOC_LABEL_FONT_SIZE} align="center" fill="#111827" />
                      <Text x={sourceMultPos.x} y={sourceMultPos.y} width={MULT_LABEL_WIDTH} text={multToText(edge.sourceMult)} fontSize={MULT_LABEL_FONT_SIZE} align="center" fill="#334155" />
                      <Text x={targetMultPos.x} y={targetMultPos.y} width={MULT_LABEL_WIDTH} text={multToText(edge.targetMult)} fontSize={MULT_LABEL_FONT_SIZE} align="center" fill="#334155" />
                    </Group>
                  );
                }

                return (
                  <Group key={edge.id}>
                    <Arrow
                      points={pathPoints}
                      stroke="#475569"
                      fill="#475569"
                      strokeWidth={1.4}
                      pointerLength={9}
                      pointerWidth={9}
                      lineCap="round"
                      lineJoin="round"
                    />
                    <Text x={midX - 60} y={midY - 19} width={120} text={edge.label || ""} fontSize={ASSOC_LABEL_FONT_SIZE} align="center" fill="#334155" />
                    <Text x={sourceMultPos.x} y={sourceMultPos.y} width={MULT_LABEL_WIDTH} text={multToText(edge.sourceMult)} fontSize={MULT_LABEL_FONT_SIZE} align="center" fill="#334155" />
                    <Text x={targetMultPos.x} y={targetMultPos.y} width={MULT_LABEL_WIDTH} text={multToText(edge.targetMult)} fontSize={MULT_LABEL_FONT_SIZE} align="center" fill="#334155" />
                  </Group>
                );
              })}

              {displayNodes.map((node) => (
                <Group
                  key={node.id}
                  x={node.x}
                  y={node.y}
                  draggable
                  onDragEnd={handleNodeDragEnd(node.id)}
                >
                  <Rect
                    x={0}
                    y={0}
                    width={node.width}
                    height={node.height}
                    cornerRadius={6}
                    fill="#f8fafc"
                    stroke="#334155"
                    strokeWidth={1.2}
                  />
                  <Rect
                    x={0}
                    y={0}
                    width={node.width}
                    height={30}
                    fill="#e2e8f0"
                    cornerRadius={6}
                  />
                  <Line points={[0, 30, node.width, 30]} stroke="#64748b" strokeWidth={1} />
                  <Text
                    x={8}
                    y={7}
                    width={node.width - 16}
                    text={node.className}
                    fontSize={11}
                    fontStyle={node.isAbstract ? "italic" : "bold"}
                    fill="#0f172a"
                    align="left"
                    listening={false}
                  />
                  {(node.attributes || []).length === 0 ? (
                    <Text
                      x={8}
                      y={38}
                      width={node.width - 16}
                      text="(no attributes)"
                      fontSize={9}
                      fill="#64748b"
                      fontStyle="italic"
                      listening={false}
                    />
                  ) : (
                    (node.attributes || []).map((a, idx) => (
                      <Text
                        key={`${node.id}-attr-${a.name}-${idx}`}
                        x={8}
                        y={38 + idx * 16}
                        width={node.width - 16}
                        text={`${a.name}: ${a.type}`}
                        fontSize={10}
                        fill="#334155"
                        listening={false}
                      />
                    ))
                  )}
                </Group>
              ))}
            </Layer>
          </Stage>
        </div>
      </div>
    </div>
  );
}

