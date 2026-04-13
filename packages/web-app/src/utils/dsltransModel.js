export const GRID_SIZE = 20;
let nodeCounter = 0;
let edgeCounter = 0;

export const NODE_KINDS = {
  MATCH: "MATCH",
  APPLY: "APPLY",
  RULE: "RULE",
};

export function createNode(kind, label, x, y, extra = {}) {
  nodeCounter += 1;
  return {
    id: `node_${nodeCounter}`,
    kind,
    label,
    x,
    y,
    width: kind === NODE_KINDS.RULE ? 260 : 140,
    height: kind === NODE_KINDS.RULE ? 180 : 60,
    ...extra,
  };
}

export function createEdge(sourceId, targetId, edgeType = "direct", label = "") {
  edgeCounter += 1;
  return {
    id: `edge_${edgeCounter}`,
    sourceId,
    targetId,
    edgeType,
    label: label || undefined,
  };
}

export function snapToGrid(value, gridSize = GRID_SIZE) {
  return Math.round(value / gridSize) * gridSize;
}

export function moveNode(node, x, y, snap = true) {
  return {
    ...node,
    x: snap ? snapToGrid(x) : x,
    y: snap ? snapToGrid(y) : y,
  };
}
