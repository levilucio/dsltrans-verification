import { useMemo, useState } from "react";
import { Arrow, Circle, Group, Layer, Line, Rect, Stage, Text } from "react-konva";
import { useDsltrans } from "@/contexts/DsltransContext";
import { NODE_KINDS } from "@/utils/dsltransModel";
import {
  getRuleBoxBounds,
  getLayerBounds,
  getContentBounds,
  RULE_LABEL_OFFSET_EXPORT as RULE_LABEL_OFFSET,
} from "@/features/layout/ruleLayout";

const PAD = 5;
const SIGNATURE_FONT = 11;
const ATTR_FONT = 10;
const SIGNATURE_HEIGHT = 20;
const ATTR_LINE_HEIGHT = 16;

function ElementNodeContent({ node }) {
  const hasStruct =
    (node.kind === NODE_KINDS.MATCH && (node.matchType || node.whereClause)) ||
    (node.kind === NODE_KINDS.APPLY && (node.attributeBindings?.length > 0));
  const signature =
    node.kind === NODE_KINDS.MATCH && node.matchType != null && node.varName != null && node.className != null
      ? `«${node.matchType}» ${node.varName} : ${node.className}`
      : node.kind === NODE_KINDS.APPLY && node.varName != null && node.className != null
        ? `${node.varName} : ${node.className}`
        : node.label;
  const attrLines =
    node.kind === NODE_KINDS.MATCH && node.whereClause
      ? [`where ${node.whereClause}`]
      : node.kind === NODE_KINDS.APPLY && node.attributeBindings?.length
        ? node.attributeBindings.map((b) => `${b.attr} = ${b.expr}`)
        : [];

  return (
    <>
      <Rect
        x={0}
        y={0}
        width={node.width}
        height={SIGNATURE_HEIGHT + 2 * PAD}
        cornerRadius={0}
        fill="transparent"
        listening={false}
      />
      <Text
        text={signature}
        x={PAD}
        y={PAD}
        width={node.width - 2 * PAD}
        height={SIGNATURE_HEIGHT}
        fontSize={SIGNATURE_FONT}
        fontStyle="bold"
        align="left"
        verticalAlign="middle"
        wrap="none"
        ellipsis={true}
        listening={false}
      />
      {attrLines.length > 0 && (
        <>
          <Line
            points={[0, SIGNATURE_HEIGHT + 2 * PAD, node.width, SIGNATURE_HEIGHT + 2 * PAD]}
            stroke="#cbd5e1"
            strokeWidth={1}
            listening={false}
          />
          {attrLines.map((line, i) => (
            <Text
              key={i}
              text={line}
              x={PAD}
              y={SIGNATURE_HEIGHT + 2 * PAD + 2 + i * ATTR_LINE_HEIGHT}
              width={node.width - 2 * PAD}
              height={ATTR_LINE_HEIGHT}
              fontSize={ATTR_FONT}
              fill="#475569"
              align="left"
              verticalAlign="middle"
              wrap="none"
              ellipsis={true}
              listening={false}
            />
          ))}
        </>
      )}
    </>
  );
}

/** Orthogonal step size for staggering multiple edges between same endpoints. */
const ORTHOGONAL_STAGGER = 18;
/** If source and target are within this distance on one axis, use a straight segment. */
const ALIGN_THRESHOLD = 14;

function edgePoints(edges, nodesById) {
  const outgoingBySource = new Map();
  const incomingByTarget = new Map();
  edges.forEach((e) => {
    if (!outgoingBySource.has(e.sourceId)) outgoingBySource.set(e.sourceId, []);
    outgoingBySource.get(e.sourceId).push(e.id);
    if (!incomingByTarget.has(e.targetId)) incomingByTarget.set(e.targetId, []);
    incomingByTarget.get(e.targetId).push(e.id);
  });

  function fanOffset(index, total, step = 8) {
    if (total <= 1) return 0;
    return (index - (total - 1) / 2) * step;
  }

  /**
   * Orthogonal route: horizontal out of source -> vertical -> horizontal into target.
   * Used when endpoints are not aligned so arcs stay readable.
   */
  function orthogonalPoints(sx, sy, tx, ty, edgeIndex, edgeCount) {
    const stagger =
      edgeCount > 1 ? (edgeIndex - (edgeCount - 1) / 2) * ORTHOGONAL_STAGGER : 0;
    const midX = (sx + tx) / 2 + stagger;
    return [sx, sy, midX, sy, midX, ty, tx, ty];
  }

  const isTraceOrBackward = (e) =>
    e.edgeType === "trace" || e.edgeType === "backward";

  return edges
    .map((edge) => {
      const src = nodesById.get(edge.sourceId);
      const tgt = nodesById.get(edge.targetId);
      if (!src || !tgt) return null;
      const leftToRight = src.x + src.width / 2 <= tgt.x + tgt.width / 2;
      const outIds = outgoingBySource.get(edge.sourceId) || [];
      const inIds = incomingByTarget.get(edge.targetId) || [];
      const outIdx = outIds.indexOf(edge.id);
      const inIdx = inIds.indexOf(edge.id);
      const srcYOffset = fanOffset(outIdx < 0 ? 0 : outIdx, outIds.length);
      const tgtYOffset = fanOffset(inIdx < 0 ? 0 : inIdx, inIds.length);
      const sx = src.x + (leftToRight ? src.width : 0);
      const sy = src.y + src.height / 2 + srcYOffset;
      const tx = tgt.x + (leftToRight ? 0 : tgt.width);
      const ty = tgt.y + tgt.height / 2 + tgtYOffset;

      let points;
      if (isTraceOrBackward(edge)) {
        // Backward/trace: direct angled line between match and apply for visibility.
        points = [sx, sy, tx, ty];
      } else if (
        Math.abs(sy - ty) <= ALIGN_THRESHOLD ||
        Math.abs(sx - tx) <= ALIGN_THRESHOLD
      ) {
        // Aligned horizontally or vertically: single straight segment.
        points = [sx, sy, tx, ty];
      } else {
        const pairKey = `${edge.sourceId}\t${edge.targetId}`;
        const samePair = edges.filter(
          (e) => `${e.sourceId}\t${e.targetId}` === pairKey,
        );
        const edgeIndex = samePair.findIndex((e) => e.id === edge.id);
        points = orthogonalPoints(
          sx,
          sy,
          tx,
          ty,
          edgeIndex < 0 ? 0 : edgeIndex,
          samePair.length,
        );
      }
      return { ...edge, points };
    })
    .filter(Boolean);
}

/** Midpoint of an edge path for label placement (supports both 2-point and 4+ point paths). */
function edgeLabelCenter(points) {
  if (points.length >= 8) {
    return { x: points[2], y: (points[1] + points[5]) / 2 };
  }
  return {
    x: (points[0] + points[2]) / 2,
    y: (points[1] + points[3]) / 2,
  };
}

export default function CanvasManager() {
  const [zoom, setZoom] = useState(1);
  const {
    nodes,
    edges,
    layers,
    selectedNodeId,
    setSelectedNodeId,
    moveCanvasNode,
    startEdgeCreation,
    completeEdgeCreation,
    pendingEdgeSourceId,
    snapToGridEnabled,
  } = useDsltrans();

  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const edgesList = edges ?? [];
  const resolvedEdges = useMemo(
    () => edgePoints(edgesList, nodeMap),
    [edgesList, nodeMap],
  );

  const ruleNodes = useMemo(
    () => nodes.filter((n) => n.kind === NODE_KINDS.RULE),
    [nodes],
  );
  const elementNodes = useMemo(
    () =>
      nodes.filter(
        (n) => n.kind === NODE_KINDS.MATCH || n.kind === NODE_KINDS.APPLY,
      ),
    [nodes],
  );

  const sortedLayers = useMemo(
    () => [...(layers || [])].sort((a, b) => a.index - b.index),
    [layers],
  );

  const contentBounds = useMemo(
    () => getContentBounds(layers || [], nodes),
    [layers, nodes],
  );
  const width = contentBounds.width;
  const height = contentBounds.height;

  const RULE_BOX_PAD = 8;

  const gridSpacing = 20;
  const gridLines = [];
  for (let x = 0; x <= width; x += gridSpacing) {
    gridLines.push(
      <Line
        key={`vx-${x}`}
        points={[x, 0, x, height]}
        stroke="#e5e7eb"
        strokeWidth={0.5}
      />,
    );
  }
  for (let y = 0; y <= height; y += gridSpacing) {
    gridLines.push(
      <Line
        key={`hy-${y}`}
        points={[0, y, width, y]}
        stroke="#e5e7eb"
        strokeWidth={0.5}
      />,
    );
  }

  return (
    <div
      className="border rounded bg-slate-50 inline-block"
      style={{ minWidth: width, minHeight: height }}
    >
      <div className="flex items-center gap-3 px-2 py-1 border-b bg-white text-xs">
        <button
          className="px-2 py-1 border rounded"
          onClick={() => setZoom((z) => Math.max(0.4, z - 0.1))}
        >
          -
        </button>
        <span>Zoom {Math.round(zoom * 100)}%</span>
        <button
          className="px-2 py-1 border rounded"
          onClick={() => setZoom((z) => Math.min(2.5, z + 0.1))}
        >
          +
        </button>
        <span className="text-slate-500">
          Snap: <strong>{snapToGridEnabled ? "on" : "off"}</strong>
        </span>
      </div>
      <Stage width={width} height={height} draggable scaleX={zoom} scaleY={zoom}>
        <Layer>{gridLines}</Layer>
        <Layer>
          {/* Layer bands: vertical stack, transformation flows top to bottom */}
          {sortedLayers.map((layer) => {
            const lb = getLayerBounds(layer, nodes);
            if (lb.width === 0 && lb.height === 0) return null;
            return (
              <Group key={`layer-${layer.id}`}>
                <Rect
                  x={lb.x}
                  y={lb.y}
                  width={lb.width}
                  height={lb.height}
                  fill="#f1f5f9"
                  stroke="#cbd5e1"
                  strokeWidth={1}
                  cornerRadius={6}
                  listening={false}
                />
                <Text
                  x={lb.x + 8}
                  y={lb.y + 10}
                  text={`Layer ${layer.index + 1}: ${layer.name}`}
                  fontSize={11}
                  fontStyle="bold"
                  fill="#475569"
                  listening={false}
                />
              </Group>
            );
          })}
          {/* Rule bounding box (square around each rule) then Match/Apply boxes */}
          {ruleNodes.map((rule) => {
            const bounds = getRuleBoxBounds(rule, nodes);
            const ruleBoxX = rule.x - RULE_BOX_PAD;
            const ruleBoxY = rule.y - RULE_LABEL_OFFSET - RULE_BOX_PAD;
            const ruleBoxW = rule.width + 2 * RULE_BOX_PAD;
            const ruleBoxH =
              rule.height + RULE_LABEL_OFFSET + 2 * RULE_BOX_PAD;
            return (
              <Group key={`rule-box-${rule.id}`}>
                <Rect
                  x={ruleBoxX}
                  y={ruleBoxY}
                  width={ruleBoxW}
                  height={ruleBoxH}
                  fill="transparent"
                  stroke="#94a3b8"
                  strokeWidth={1.5}
                  cornerRadius={6}
                  listening={false}
                />
                <Rect
                  x={bounds.match.x}
                  y={bounds.match.y}
                  width={bounds.match.width}
                  height={bounds.match.height}
                  fill="#ffffff"
                  stroke="#94a3b8"
                  strokeWidth={1}
                  cornerRadius={4}
                  listening={false}
                />
                <Text
                  x={bounds.match.x}
                  y={bounds.match.y + 5}
                  text="Match"
                  fontSize={11}
                  fill="#64748b"
                  width={bounds.match.width}
                  align="center"
                  listening={false}
                />
                <Rect
                  x={bounds.apply.x}
                  y={bounds.apply.y}
                  width={bounds.apply.width}
                  height={bounds.apply.height}
                  fill="#e2e8f0"
                  stroke="#94a3b8"
                  strokeWidth={1}
                  cornerRadius={4}
                  listening={false}
                />
                <Text
                  x={bounds.apply.x}
                  y={bounds.apply.y + 5}
                  text="Apply"
                  fontSize={11}
                  fill="#64748b"
                  width={bounds.apply.width}
                  align="center"
                  listening={false}
                />
                <Text
                  x={rule.x}
                  y={rule.y - RULE_LABEL_OFFSET}
                  text={rule.label}
                  fontSize={12}
                  fontStyle="bold"
                  fill="#1e293b"
                  listening={false}
                />
              </Group>
            );
          })}
        </Layer>
        <Layer listening={false}>
          {/* Edges: backward/trace = dashed arrows; direct = solid */}
          {resolvedEdges.map((edge) => {
            const isTraceOrBackward =
              edge.edgeType === "trace" || edge.edgeType === "backward";
            const stroke =
              edge.edgeType === "backward"
                ? "#ef4444"
                : edge.edgeType === "trace"
                  ? "#8b5cf6"
                  : "#334155";
            return (
              <Group key={edge.id} listening={false}>
                <Arrow
                  points={edge.points}
                  stroke={stroke}
                  fill={stroke}
                  strokeWidth={2}
                  pointerLength={10}
                  pointerWidth={10}
                  tension={0}
                  dash={isTraceOrBackward ? [8, 4] : undefined}
                />
              </Group>
            );
          })}
        </Layer>
        <Layer>
          {/* Element nodes (match/apply) only */}
          {elementNodes.map((node) => {
            const selected = node.id === selectedNodeId;
            const isPending = node.id === pendingEdgeSourceId;
            return (
              <Group
                key={node.id}
                x={node.x}
                y={node.y}
                draggable
                onClick={() => setSelectedNodeId(node.id)}
                onTap={() => setSelectedNodeId(node.id)}
                onDragEnd={(evt) =>
                  moveCanvasNode(node.id, evt.target.x(), evt.target.y())
                }
                onDblClick={() => startEdgeCreation(node.id)}
                onMouseUp={() => completeEdgeCreation(node.id)}
              >
                <Rect
                  width={node.width}
                  height={node.height}
                  cornerRadius={4}
                  fill={
                    node.kind === NODE_KINDS.MATCH ? "#ffffff" : "#fefce8"
                  }
                  stroke={
                    isPending ? "#7c3aed" : selected ? "#0ea5e9" : "#334155"
                  }
                  strokeWidth={isPending ? 3 : selected ? 2 : 1}
                />
                <ElementNodeContent node={node} />
                {isPending && (
                  <Circle
                    x={node.width - 10}
                    y={10}
                    radius={5}
                    fill="#7c3aed"
                  />
                )}
              </Group>
            );
          })}
        </Layer>
        <Layer listening={false}>
          {/* Draw direct-edge labels above nodes so they remain visible. */}
          {resolvedEdges
            .filter((edge) => edge.edgeType !== "trace" && edge.edgeType !== "backward" && edge.label)
            .map((edge) => {
              const edgeLabel = edge.label || "";
              const labelWidth = Math.max(
                64,
                Math.min(260, edgeLabel.length * 7 + 18),
              );
              const { x: midX, y: midY } = edgeLabelCenter(edge.points);
              const labelY = midY - 18;
              return (
                <Group key={`${edge.id}-label`} listening={false}>
                  <Text
                    x={midX - labelWidth / 2}
                    y={labelY}
                    text={edgeLabel}
                    fontSize={10}
                    fill="#0f172a"
                    width={labelWidth}
                    align="center"
                    listening={false}
                  />
                </Group>
              );
            })}
        </Layer>
      </Stage>
    </div>
  );
}
