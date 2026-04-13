import { useMemo } from "react";
import { Arrow, Group, Layer, Rect, Stage, Text } from "react-konva";

/** Same symbology as rule editor: Match = white, Apply = gray; trace = dashed purple. */
const STROKE = "#94a3b8";
const MATCH_FILL = "#ffffff";
const APPLY_FILL = "#e2e8f0";
const MATCH_NODE_FILL = "#ffffff";
const APPLY_NODE_FILL = "#fefce8";
const TRACE_STROKE = "#8b5cf6";
const REL_STROKE = "#0ea5e9";

const ELEMENT_W = 88;
const ELEMENT_H = 32;
const BOX_PAD = 8;
const GAP_ELEMENTS = 14;
const GAP_ROWS = 10;
const SECTION_LABEL_H = 14;
const SECTION_GAP = 18;
const TOP_PAD = 4;
const BOTTOM_PAD = 8;
const BOX_MIN_WIDTH = 120;

function getPropertyNodeHeight(node, isPre) {
  const hasExtra =
    (isPre && node.whereClause) ||
    (!isPre && (node.attributeBindings?.length ?? 0) > 0);
  return hasExtra ? ELEMENT_H + 14 : ELEMENT_H;
}

function sectionCell(index, rowCount) {
  if (rowCount <= 1) return { row: 0, col: index };
  return { row: index % rowCount, col: Math.floor(index / rowCount) };
}

function computeSectionGeometry(nodes, isPre) {
  const count = nodes.length;
  if (count === 0) {
    return {
      rowCount: 1,
      contentWidth: 0,
      rowOffsets: [0],
      boxWidth: BOX_MIN_WIDTH,
      boxHeight: SECTION_LABEL_H + ELEMENT_H + 2 * BOX_PAD,
    };
  }
  const rowCount = count <= 2 ? 1 : 2;
  const columns = rowCount === 1 ? count : Math.ceil(count / rowCount);
  const rowHeights = new Array(rowCount).fill(0);
  nodes.forEach((n, idx) => {
    const { row } = sectionCell(idx, rowCount);
    rowHeights[row] = Math.max(rowHeights[row], getPropertyNodeHeight(n, isPre));
  });
  const rowOffsets = [];
  let y = 0;
  for (let i = 0; i < rowHeights.length; i += 1) {
    rowOffsets.push(y);
    y += rowHeights[i] + (i < rowHeights.length - 1 ? GAP_ROWS : 0);
  }
  const contentWidth = columns * ELEMENT_W + Math.max(columns - 1, 0) * GAP_ELEMENTS;
  const contentHeight = rowHeights.reduce((acc, h) => acc + h, 0) + Math.max(rowCount - 1, 0) * GAP_ROWS;
  return {
    rowCount,
    contentWidth,
    rowOffsets,
    boxWidth: Math.max(BOX_MIN_WIDTH, contentWidth + 2 * BOX_PAD),
    boxHeight: SECTION_LABEL_H + contentHeight + 2 * BOX_PAD,
  };
}

function relationLabel(r) {
  if (r.assocName) return r.assocName;
  if (r.relationVar) return r.relationVar.replace(/Link$/, "");
  return "link";
}

function nodeAnchors(pos, isPre) {
  const h = getPropertyNodeHeight(pos.node, isPre);
  const midX = pos.x + ELEMENT_W / 2;
  const midY = pos.y + h / 2;
  return [
    { x: midX, y: pos.y, side: "top" },
    { x: pos.x + ELEMENT_W, y: midY, side: "right" },
    { x: midX, y: pos.y + h, side: "bottom" },
    { x: pos.x, y: midY, side: "left" },
  ];
}

function routeBetweenNodes(srcPos, tgtPos, srcIsPre, tgtIsPre) {
  const srcAnchors = nodeAnchors(srcPos, srcIsPre);
  const tgtAnchors = nodeAnchors(tgtPos, tgtIsPre);
  let best = null;
  for (const s of srcAnchors) {
    for (const t of tgtAnchors) {
      const d = Math.abs(s.x - t.x) + Math.abs(s.y - t.y);
      if (!best || d < best.dist) best = { s, t, dist: d };
    }
  }
  const sx = best.s.x;
  const sy = best.s.y;
  const tx = best.t.x;
  const ty = best.t.y;
  const alignedH = Math.abs(sy - ty) < 8;
  const alignedV = Math.abs(sx - tx) < 8;
  if (alignedH || alignedV) {
    return [sx, sy, tx, ty];
  }
  if (Math.abs(sx - tx) >= Math.abs(sy - ty)) {
    const mx = (sx + tx) / 2;
    return [sx, sy, mx, sy, mx, ty, tx, ty];
  }
  const my = (sy + ty) / 2;
  return [sx, sy, sx, my, tx, my, tx, ty];
}

function edgeLabelPoint(points) {
  if (!points || points.length < 4) return { x: 0, y: 0 };
  if (points.length >= 8) {
    return {
      x: points[2],
      y: (points[1] + points[5]) / 2,
    };
  }
  return {
    x: (points[0] + points[2]) / 2,
    y: (points[1] + points[3]) / 2,
  };
}

function PropertyElementNode({ node, isPre, x, y }) {
  const fill = isPre ? MATCH_NODE_FILL : APPLY_NODE_FILL;
  const signature =
    isPre && node.matchType != null
      ? `«${node.matchType}» ${node.varName} : ${node.className}`
      : `${node.varName} : ${node.className}`;
  const h = getPropertyNodeHeight(node, isPre);

  return (
    <Group x={x} y={y} listening={false}>
      <Rect
        width={ELEMENT_W}
        height={h}
        cornerRadius={4}
        fill={fill}
        stroke={STROKE}
        strokeWidth={1}
        listening={false}
      />
      <Text
        x={4}
        y={4}
        text={signature}
        width={ELEMENT_W - 8}
        height={ELEMENT_H - 8}
        fontSize={9}
        fontStyle="bold"
        align="left"
        wrap="none"
        ellipsis={true}
        listening={false}
      />
      {isPre && node.whereClause && (
        <Text
          x={4}
          y={ELEMENT_H - 2}
          text={`where ${node.whereClause}`}
          width={ELEMENT_W - 8}
          height={14}
          fontSize={8}
          fill="#475569"
          align="left"
          wrap="none"
          ellipsis={true}
          listening={false}
        />
      )}
    </Group>
  );
}

export default function PropertyGraphView({
  preNodes,
  postNodes,
  preRelations = [],
  postRelations = [],
  traceEdges = [],
  width = 320,
  height: heightProp,
}) {
  const { layout, height, canvasWidth } = useMemo(() => {
    const preGeom = computeSectionGeometry(preNodes, true);
    const postGeom = computeSectionGeometry(postNodes, false);
    const boxW = Math.max(preGeom.boxWidth, postGeom.boxWidth);
    const canvasW = Math.max(width, boxW + 24);
    const boxX = (canvasW - boxW) / 2;
    const preBoxY = TOP_PAD;
    const postBoxY = preBoxY + preGeom.boxHeight + SECTION_GAP;
    const computedHeight = heightProp ?? postBoxY + postGeom.boxHeight + BOTTOM_PAD;

    const preStartX = boxX + (boxW - preGeom.contentWidth) / 2;
    const postStartX = boxX + (boxW - postGeom.contentWidth) / 2;
    const preNodePositions = preNodes.map((n, i) => {
      const { row, col } = sectionCell(i, preGeom.rowCount);
      return {
        node: n,
        x: preStartX + col * (ELEMENT_W + GAP_ELEMENTS),
        y: preBoxY + SECTION_LABEL_H + BOX_PAD + (preGeom.rowOffsets[row] ?? 0),
      };
    });
    const postNodePositions = postNodes.map((n, i) => {
      const { row, col } = sectionCell(i, postGeom.rowCount);
      return {
        node: n,
        x: postStartX + col * (ELEMENT_W + GAP_ELEMENTS),
        y: postBoxY + SECTION_LABEL_H + BOX_PAD + (postGeom.rowOffsets[row] ?? 0),
      };
    });

    const preRelationEdges = preRelations
      .map((r) => {
        const src = preNodePositions.find((p) => p.node.varName === r.sourceVar);
        const tgt = preNodePositions.find((p) => p.node.varName === r.targetVar);
        if (!src || !tgt) return null;
        const points = routeBetweenNodes(src, tgt, true, true);
        const center = edgeLabelPoint(points);
        const label = relationLabel(r);
        return {
          points,
          label,
          lx: center.x + 3,
          ly: center.y - 8,
        };
      })
      .filter(Boolean);

    const postRelationEdges = postRelations
      .map((r) => {
        const src = postNodePositions.find((p) => p.node.varName === r.sourceVar);
        const tgt = postNodePositions.find((p) => p.node.varName === r.targetVar);
        if (!src || !tgt) return null;
        const points = routeBetweenNodes(src, tgt, false, false);
        const center = edgeLabelPoint(points);
        const label = relationLabel(r);
        return {
          points,
          label,
          lx: center.x + 3,
          ly: center.y - 8,
        };
      })
      .filter(Boolean);

    const traceEdgeItems = traceEdges.map((e) => {
      const prePos = preNodePositions.find(
        (p) => p.node.varName === e.sourceVar || (p.node.varName && p.node.varName.trim() === e.sourceVar)
      );
      const postPos = postNodePositions.find(
        (p) => p.node.varName === e.targetVar || (p.node.varName && p.node.varName.trim() === e.targetVar)
      );
      if (!prePos || !postPos) return null;
      const sx = prePos.x + ELEMENT_W / 2;
      const sy = prePos.y + ELEMENT_H;
      const tx = postPos.x + ELEMENT_W / 2;
      const ty = postPos.y;
      return {
        points: [sx, sy, tx, ty],
        label: "trace",
        lx: (sx + tx) / 2 + 4,
        ly: (sy + ty) / 2 - 6,
      };
    }).filter(Boolean);

    return {
      layout: {
        preBox: { x: boxX, y: preBoxY, w: boxW, h: preGeom.boxHeight },
        postBox: { x: boxX, y: postBoxY, w: boxW, h: postGeom.boxHeight },
        preNodePositions,
        postNodePositions,
        preRelationEdges,
        postRelationEdges,
        traceEdgeItems,
      },
      height: computedHeight,
      canvasWidth: canvasW,
    };
  }, [preNodes, postNodes, preRelations, postRelations, traceEdges, width, heightProp]);

  return (
    <Stage width={canvasWidth} height={height} listening={false}>
      <Layer listening={false}>
        <Rect
          x={layout.preBox.x}
          y={layout.preBox.y}
          width={layout.preBox.w}
          height={layout.preBox.h}
          fill={MATCH_FILL}
          stroke={STROKE}
          strokeWidth={1}
          cornerRadius={4}
          listening={false}
        />
        <Text
          x={layout.preBox.x}
          y={layout.preBox.y + 3}
          text="Precondition"
          fontSize={10}
          fill="#64748b"
          width={layout.preBox.w}
          align="center"
          listening={false}
        />
        <Rect
          x={layout.postBox.x}
          y={layout.postBox.y}
          width={layout.postBox.w}
          height={layout.postBox.h}
          fill={APPLY_FILL}
          stroke={STROKE}
          strokeWidth={1}
          cornerRadius={4}
          listening={false}
        />
        <Text
          x={layout.postBox.x}
          y={layout.postBox.y + 3}
          text="Postcondition"
          fontSize={10}
          fill="#64748b"
          width={layout.postBox.w}
          align="center"
          listening={false}
        />
        {layout.preNodePositions.map(({ node, x, y }) => (
          <PropertyElementNode
            key={node.id}
            node={node}
            isPre
            x={x}
            y={y}
          />
        ))}
        {layout.postNodePositions.map(({ node, x, y }) => (
          <PropertyElementNode
            key={node.id}
            node={node}
            isPre={false}
            x={x}
            y={y}
          />
        ))}
        {layout.preRelationEdges.map(({ points, label, lx, ly }, i) => (
          <Group key={`pre-rel-${i}`} listening={false}>
            <Arrow
              points={points}
              stroke={REL_STROKE}
              fill={REL_STROKE}
              strokeWidth={1.5}
              pointerLength={6}
              pointerWidth={5}
              listening={false}
              lineCap="round"
              lineJoin="round"
            />
            <Text
              x={lx}
              y={ly}
              text={label}
              fontSize={8}
              fill={REL_STROKE}
              listening={false}
            />
          </Group>
        ))}
        {layout.postRelationEdges.map(({ points, label, lx, ly }, i) => (
          <Group key={`post-rel-${i}`} listening={false}>
            <Arrow
              points={points}
              stroke={REL_STROKE}
              fill={REL_STROKE}
              strokeWidth={1.5}
              pointerLength={6}
              pointerWidth={5}
              listening={false}
              lineCap="round"
              lineJoin="round"
            />
            <Text
              x={lx}
              y={ly}
              text={label}
              fontSize={8}
              fill={REL_STROKE}
              listening={false}
            />
          </Group>
        ))}
        {layout.traceEdgeItems.map(({ points, label, lx, ly }, i) => (
          <Group key={`trace-${i}`} listening={false}>
            <Arrow
              points={points}
              stroke={TRACE_STROKE}
              fill={TRACE_STROKE}
              strokeWidth={2.5}
              pointerLength={8}
              pointerWidth={6}
              dash={[8, 4]}
              listening={false}
              lineCap="round"
              lineJoin="round"
            />
            <Text
              x={lx}
              y={ly}
              text={label}
              fontSize={8}
              fill={TRACE_STROKE}
              listening={false}
            />
          </Group>
        ))}
      </Layer>
    </Stage>
  );
}
