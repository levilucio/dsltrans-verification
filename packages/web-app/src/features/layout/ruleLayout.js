import { NODE_KINDS } from "@/utils/dsltransModel";

const ELEMENT_WIDTH = 100;
const ELEMENT_HEIGHT = 44;
const ELEMENT_ATTR_LINE_HEIGHT = 18;
const BOX_PADDING = 16;
const GAP_ELEMENTS = 42;
const GAP_ELEMENT_ROWS = 18;
const GAP_MATCH_APPLY = 8;
const BOX_MIN_WIDTH = 120;
const RULE_LABEL_HEIGHT = 0;
/** Vertical space reserved for "Match" / "Apply" keyword above element row */
const SECTION_LABEL_HEIGHT = 18;

/**
 * Height of a match/apply element node (UML-style: signature + optional attribute compartment).
 */
export function getElementNodeHeight(node) {
  if (!node || (node.kind !== NODE_KINDS.MATCH && node.kind !== NODE_KINDS.APPLY)) {
    return ELEMENT_HEIGHT;
  }
  let extraLines = 0;
  if (node.kind === NODE_KINDS.MATCH && node.whereClause) extraLines += 1;
  if (node.kind === NODE_KINDS.APPLY && node.attributeBindings?.length)
    extraLines += node.attributeBindings.length;
  return ELEMENT_HEIGHT + extraLines * ELEMENT_ATTR_LINE_HEIGHT;
}

export const BOX_DIMS = {
  ELEMENT_WIDTH,
  ELEMENT_HEIGHT,
  BOX_PADDING,
  GAP_ELEMENTS,
  GAP_MATCH_APPLY,
  BOX_MIN_WIDTH,
};

function sectionCell(index, rowCount) {
  if (rowCount <= 1) return { row: 0, col: index };
  return { row: index % rowCount, col: Math.floor(index / rowCount) };
}

/**
 * Compute section geometry (match/apply) with a staggered two-row layout for
 * larger sections, which reduces horizontal edge overlap.
 */
function computeSectionGeometry(nodes) {
  const count = nodes.length;
  if (count === 0) {
    return {
      count: 0,
      rowCount: 1,
      columns: 0,
      rowHeights: [ELEMENT_HEIGHT],
      rowOffsets: [0],
      contentWidth: 0,
      contentHeight: ELEMENT_HEIGHT,
      boxWidth: BOX_MIN_WIDTH,
      boxHeight: SECTION_LABEL_HEIGHT + ELEMENT_HEIGHT + 2 * BOX_PADDING + RULE_LABEL_HEIGHT,
    };
  }

  const rowCount = count <= 2 ? 1 : 2;
  const columns = rowCount === 1 ? count : Math.ceil(count / rowCount);
  const rowHeights = new Array(rowCount).fill(0);
  nodes.forEach((n, idx) => {
    const { row } = sectionCell(idx, rowCount);
    rowHeights[row] = Math.max(rowHeights[row], getElementNodeHeight(n));
  });
  for (let i = 0; i < rowHeights.length; i += 1) {
    rowHeights[i] = Math.max(rowHeights[i], ELEMENT_HEIGHT);
  }

  const rowOffsets = [];
  let offset = 0;
  for (let i = 0; i < rowHeights.length; i += 1) {
    rowOffsets.push(offset);
    offset += rowHeights[i] + (i < rowHeights.length - 1 ? GAP_ELEMENT_ROWS : 0);
  }

  const contentWidth = columns * ELEMENT_WIDTH + Math.max(columns - 1, 0) * GAP_ELEMENTS;
  const contentHeight = rowHeights.reduce((acc, h) => acc + h, 0) + Math.max(rowCount - 1, 0) * GAP_ELEMENT_ROWS;
  const boxWidth = Math.max(BOX_MIN_WIDTH, contentWidth + 2 * BOX_PADDING);
  const boxHeight = SECTION_LABEL_HEIGHT + contentHeight + 2 * BOX_PADDING + RULE_LABEL_HEIGHT;

  return {
    count,
    rowCount,
    columns,
    rowHeights,
    rowOffsets,
    contentWidth,
    contentHeight,
    boxWidth,
    boxHeight,
  };
}

export const BOX_HEIGHT =
  SECTION_LABEL_HEIGHT + ELEMENT_HEIGHT + 2 * BOX_PADDING + RULE_LABEL_HEIGHT;

const RULE_GAP = 24;
const LAYER_GAP = 48;
const MARGIN_X = 60;
const MARGIN_Y = 56;
const RULE_LABEL_OFFSET = 18;
const LAYER_LABEL_GAP = 10;
/** Extra vertical space between layer name and the first rule's Match box */
const LAYER_TO_RULE_GAP = 12;

/**
 * Layout nodes by rule: layers stacked vertically (transformation flows top to bottom).
 * Within each layer, rules are placed horizontally with no overlap.
 * Match box (white) and Apply box (gray), same size, vertically aligned.
 */
export function ruleBasedLayout(layers, nodes) {
  const rules = nodes.filter((n) => n.kind === NODE_KINDS.RULE);
  const sortedLayers = [...layers].sort((a, b) => a.index - b.index);

  // First pass: compute each rule's dimensions (no positions yet)
  const ruleDims = new Map();
  rules.forEach((rule) => {
    const matchNodes = nodes.filter(
      (n) => n.parentRuleId === rule.id && n.kind === NODE_KINDS.MATCH,
    );
    const applyNodes = nodes.filter(
      (n) => n.parentRuleId === rule.id && n.kind === NODE_KINDS.APPLY,
    );
    const matchGeom = computeSectionGeometry(matchNodes);
    const applyGeom = computeSectionGeometry(applyNodes);
    const ruleW = Math.max(matchGeom.boxWidth, applyGeom.boxWidth);
    const ruleH = matchGeom.boxHeight + GAP_MATCH_APPLY + applyGeom.boxHeight;
    ruleDims.set(rule.id, {
      width: ruleW,
      height: ruleH,
      matchGeom,
      applyGeom,
    });
  });

  // Second pass: assign positions by layer (vertical stack), then rules within layer (horizontal, no overlap)
  const ruleLayout = new Map();
  let layerY = MARGIN_Y;

  sortedLayers.forEach((layer) => {
    const layerRules = rules.filter((r) => r.layerId === layer.id);
    if (layerRules.length === 0) return;

    layerY += LAYER_LABEL_GAP;
    let ruleX = MARGIN_X;
    const layerHeights = [];

    layerRules.forEach((rule) => {
      const dims = ruleDims.get(rule.id);
      if (!dims) return;
      ruleLayout.set(rule.id, {
        x: ruleX,
        y: layerY + LAYER_TO_RULE_GAP + RULE_LABEL_OFFSET,
        width: dims.width,
        height: dims.height,
        matchGeom: dims.matchGeom,
        applyGeom: dims.applyGeom,
      });
      layerHeights.push(dims.height + LAYER_TO_RULE_GAP + RULE_LABEL_OFFSET);
      ruleX += dims.width + RULE_GAP;
    });

    const layerHeight = Math.max(...layerHeights, 0);
    layerY += layerHeight + LAYER_GAP + LAYER_LABEL_GAP;
  });

  // Second pass: update all nodes
  return nodes.map((node) => {
    if (node.kind === NODE_KINDS.RULE) {
      const layout = ruleLayout.get(node.id);
      if (!layout) return node;
      return {
        ...node,
        x: layout.x,
        y: layout.y,
        width: layout.width,
        height: layout.height,
      };
    }

    if (node.kind === NODE_KINDS.MATCH || node.kind === NODE_KINDS.APPLY) {
      const layout = ruleLayout.get(node.parentRuleId);
      if (!layout) return node;

      const siblings =
        node.kind === NODE_KINDS.MATCH
          ? nodes.filter(
              (n) =>
                n.parentRuleId === node.parentRuleId && n.kind === NODE_KINDS.MATCH,
            )
          : nodes.filter(
              (n) =>
                n.parentRuleId === node.parentRuleId && n.kind === NODE_KINDS.APPLY,
            );
      const index = siblings.findIndex((n) => n.id === node.id);
      if (index < 0) return node;

      const isApply = node.kind === NODE_KINDS.APPLY;
      const sectionGeom = isApply ? layout.applyGeom : layout.matchGeom;
      const matchBoxH = layout.matchGeom?.boxHeight ?? BOX_HEIGHT;
      const baseY = isApply
        ? layout.y + matchBoxH + GAP_MATCH_APPLY + SECTION_LABEL_HEIGHT + BOX_PADDING
        : layout.y + SECTION_LABEL_HEIGHT + BOX_PADDING;
      const contentW = sectionGeom?.contentWidth ?? 0;
      const startX = layout.x + (layout.width - contentW) / 2;
      const { row, col } = sectionCell(index, sectionGeom?.rowCount ?? 1);
      const rowOffset = sectionGeom?.rowOffsets?.[row] ?? 0;
      const x = startX + col * (ELEMENT_WIDTH + GAP_ELEMENTS);
      const y = baseY + rowOffset;
      const height = getElementNodeHeight(node);

      return {
        ...node,
        x,
        y,
        width: ELEMENT_WIDTH,
        height,
      };
    }

    return node;
  });
}

export const RULE_LABEL_OFFSET_EXPORT = RULE_LABEL_OFFSET;

/**
 * Get Match and Apply box bounds for a rule (for drawing container rects).
 */
export function getRuleBoxBounds(rule, nodes) {
  const matchNodes = nodes.filter(
    (n) => n.parentRuleId === rule.id && n.kind === NODE_KINDS.MATCH,
  );
  const applyNodes = nodes.filter(
    (n) => n.parentRuleId === rule.id && n.kind === NODE_KINDS.APPLY,
  );
  const matchGeom = computeSectionGeometry(matchNodes);
  const applyGeom = computeSectionGeometry(applyNodes);
  const boxW = rule.width ?? Math.max(matchGeom.boxWidth, applyGeom.boxWidth);
  const matchBoxH = matchGeom.boxHeight;
  const applyBoxH = applyGeom.boxHeight;
  return {
    match: { x: rule.x, y: rule.y, width: boxW, height: matchBoxH },
    apply: {
      x: rule.x,
      y: rule.y + matchBoxH + GAP_MATCH_APPLY,
      width: boxW,
      height: applyBoxH,
    },
  };
}

const LAYER_BAND_PAD = 12;
const LAYER_LABEL_TOP_PAD = 26;

/**
 * Get bounding box for a layer (all rules in that layer) for drawing layer band.
 */
export function getLayerBounds(layer, nodes) {
  const rules = nodes.filter(
    (n) => n.kind === NODE_KINDS.RULE && n.layerId === layer.id,
  );
  if (rules.length === 0)
    return { x: 0, y: 0, width: 0, height: 0 };
  const left = Math.min(...rules.map((r) => r.x));
  const top = Math.min(...rules.map((r) => r.y)) - RULE_LABEL_OFFSET;
  const right = Math.max(...rules.map((r) => r.x + r.width));
  const bottom = Math.max(...rules.map((r) => r.y + r.height));
  return {
    x: left - LAYER_BAND_PAD,
    y: top - LAYER_BAND_PAD - LAYER_LABEL_TOP_PAD,
    width: right - left + 2 * LAYER_BAND_PAD,
    height: bottom - top + 2 * LAYER_BAND_PAD + LAYER_LABEL_TOP_PAD,
  };
}

const CONTENT_MARGIN = 80;

/**
 * Get the full content bounds so the canvas can size to fit the entire transformation.
 */
export function getContentBounds(layers, nodes) {
  const rules = nodes.filter((n) => n.kind === NODE_KINDS.RULE);
  if (rules.length === 0) {
    return { width: 1280, height: 800 };
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  rules.forEach((r) => {
    const ruleTop = r.y - RULE_LABEL_OFFSET_EXPORT;
    minX = Math.min(minX, r.x);
    minY = Math.min(minY, ruleTop);
    maxX = Math.max(maxX, r.x + r.width);
    maxY = Math.max(maxY, r.y + r.height);
  });
  const sortedLayers = [...layers].sort((a, b) => a.index - b.index);
  sortedLayers.forEach((layer) => {
    const lb = getLayerBounds(layer, nodes);
    if (lb.width > 0 && lb.height > 0) {
      minX = Math.min(minX, lb.x);
      minY = Math.min(minY, lb.y);
      maxX = Math.max(maxX, lb.x + lb.width);
      maxY = Math.max(maxY, lb.y + lb.height);
    }
  });
  const width = Math.max(1280, maxX - minX + 2 * CONTENT_MARGIN);
  const height = Math.max(800, maxY - minY + 2 * CONTENT_MARGIN);
  return { width, height, minX, minY, maxX, maxY };
}
