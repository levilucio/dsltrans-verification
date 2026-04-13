import { useCallback, useEffect, useMemo, useState } from "react";
import { Arrow, Group, Layer, Rect, Stage, Text } from "react-konva";

const NODE_WIDTH = 100;
const NODE_HEIGHT = 60;
const DEFAULT_WIDTH = 580;
const DEFAULT_HEIGHT = 380;
const CONTENT_PADDING = 80;

function getModelGraphContentBounds(nodes) {
  if (!nodes.length) return { width: 0, height: 0 };
  const minX = Math.min(...nodes.map((n) => n.x ?? 0));
  const minY = Math.min(...nodes.map((n) => n.y ?? 0));
  const maxX = Math.max(...nodes.map((n) => (n.x ?? 0) + NODE_WIDTH));
  const maxY = Math.max(...nodes.map((n) => (n.y ?? 0) + NODE_HEIGHT));
  return {
    width: maxX - minX + CONTENT_PADDING,
    height: maxY - minY + CONTENT_PADDING,
  };
}

export default function ModelGraphView({
  graph,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  fullScreenMode = false,
}) {
  const [zoom, setZoom] = useState(1);
  const [nodePositions, setNodePositions] = useState({});
  useEffect(() => setNodePositions({}), [graph]);
  const displayNodes = useMemo(
    () =>
      graph.nodes.map((n) => ({
        ...n,
        x: nodePositions[n.id]?.x ?? n.x ?? 0,
        y: nodePositions[n.id]?.y ?? n.y ?? 0,
      })),
    [graph.nodes, nodePositions],
  );
  const nodeMap = useMemo(() => new Map(displayNodes.map((n) => [n.id, n])), [displayNodes]);
  const handleNodeDragEnd = useCallback((nodeId) => (e) => {
    setNodePositions((prev) => ({
      ...prev,
      [nodeId]: { x: e.target.x(), y: e.target.y() },
    }));
  }, []);

  const contentBounds = useMemo(() => getModelGraphContentBounds(displayNodes), [displayNodes]);
  const stageWidth = Math.max(width, contentBounds.width);
  const stageHeight = Math.max(height, contentBounds.height);

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
      <div
        className="overflow-auto min-h-0 flex-1 min-h-[200px]"
        style={scrollContainerStyle}
      >
        <div style={{ width: scaledWidth, height: scaledHeight, minWidth: scaledWidth, minHeight: scaledHeight }}>
          <Stage
            width={scaledWidth}
            height={scaledHeight}
            scaleX={zoom}
            scaleY={zoom}
          >
            <Layer>
              {graph.edges.map((edge) => {
                const src = nodeMap.get(edge.sourceId);
                const tgt = nodeMap.get(edge.targetId);
                if (!src || !tgt) return null;
                const sx = (src.x ?? 0) + NODE_WIDTH / 2;
                const sy = (src.y ?? 0) + NODE_HEIGHT / 2;
                const tx = (tgt.x ?? 0) + NODE_WIDTH / 2;
                const ty = (tgt.y ?? 0) + NODE_HEIGHT / 2;
                const midX = (sx + tx) / 2;
                const midY = (sy + ty) / 2;
                const label = edge.assocName || (edge.edgeType === "trace" ? "trace" : "link");
                const stroke = edge.edgeType === "trace" ? "#7c3aed" : "#334155";
                return (
                  <Group key={edge.id}>
                    <Arrow
                      points={[sx, sy, tx, ty]}
                      stroke={stroke}
                      fill={stroke}
                      dash={edge.edgeType === "trace" ? [6, 4] : undefined}
                    />
                    <Text
                      x={midX - 40}
                      y={midY - 6}
                      width={80}
                      text={label}
                      fontSize={9}
                      fontStyle="normal"
                      fill={stroke}
                      align="center"
                      listening={false}
                    />
                  </Group>
                );
              })}
              {displayNodes.map((node) => (
                <Group
                  key={node.id}
                  x={node.x ?? 0}
                  y={node.y ?? 0}
                  draggable
                  onDragEnd={handleNodeDragEnd(node.id)}
                >
                  <Rect
                    x={0}
                    y={0}
                    width={NODE_WIDTH}
                    height={NODE_HEIGHT}
                    cornerRadius={6}
                    fill="#f8fafc"
                    stroke="#475569"
                  />
                  <Text
                    x={5}
                    y={5}
                    width={NODE_WIDTH - 10}
                    text={`${node.className}\n${node.id}`}
                    fontSize={10}
                    listening={false}
                  />
                </Group>
              ))}
            </Layer>
          </Stage>
        </div>
      </div>
    </div>
  );
}
