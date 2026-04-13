const CLASS_WIDTH = 230;
const HEADER_HEIGHT = 28;
const ATTR_LINE_HEIGHT = 16;
const NODE_PADDING = 8;
const X_GAP = 90;
const Y_GAP = 90;
const MARGIN_X = 50;
const MARGIN_Y = 40;

function classNodeHeight(cls) {
  const attrCount = (cls.attributes || []).length;
  return HEADER_HEIGHT + NODE_PADDING * 2 + Math.max(attrCount, 1) * ATTR_LINE_HEIGHT + NODE_PADDING;
}

/** Parent -> children (inheritance only). Roots have no parent. */
function buildInheritanceTree(classes) {
  const byId = new Map(classes.map((c) => [c.id, c]));
  const children = new Map(classes.map((c) => [c.id, []]));
  const roots = [];
  classes.forEach((c) => {
    if (!c.parent || !byId.has(c.parent)) {
      roots.push(c.id);
      return;
    }
    if (!children.has(c.parent)) children.set(c.parent, []);
    children.get(c.parent).push(c.id);
  });
  roots.sort((a, b) => String(a).localeCompare(String(b)));
  children.forEach((arr) => arr.sort((a, b) => String(a).localeCompare(String(b))));
  return { byId, children, roots };
}

function subtreeWidth(classId, children, byId) {
  const kids = children.get(classId) || [];
  if (kids.length === 0) return CLASS_WIDTH + X_GAP;
  const sum = kids.reduce((acc, id) => acc + subtreeWidth(id, children, byId), 0);
  return sum + (kids.length - 1) * X_GAP;
}

function placeNode(classId, left, right, level, nodesById, children, subtreeWidths, rowStep, out) {
  const cls = nodesById.get(classId);
  if (!cls) return;
  const centerX = (left + right) / 2;
  const x = centerX - CLASS_WIDTH / 2;
  const y = MARGIN_Y + level * rowStep;
  const h = classNodeHeight(cls);
  out.push({
    id: cls.id,
    className: cls.name,
    isAbstract: Boolean(cls.isAbstract),
    parent: cls.parent || null,
    attributes: cls.attributes || [],
    x: Math.round(x),
    y: Math.round(y),
    width: CLASS_WIDTH,
    height: h,
  });
  const kids = children.get(classId) || [];
  if (kids.length === 0) return;
  const totalChildWidth =
    kids.reduce((acc, id) => acc + (subtreeWidths.get(id) ?? CLASS_WIDTH + X_GAP), 0) + (kids.length - 1) * X_GAP;
  let start = centerX - totalChildWidth / 2;
  kids.forEach((childId) => {
    const cw = subtreeWidths.get(childId) ?? CLASS_WIDTH + X_GAP;
    placeNode(childId, start, start + cw, level + 1, nodesById, children, subtreeWidths, rowStep, out);
    start += cw + X_GAP;
  });
}

function buildAssociationNeighbors(classes, assocEdges) {
  const neighbors = new Map(classes.map((c) => [c.id, new Set()]));
  assocEdges.forEach((edge) => {
    if (!neighbors.has(edge.sourceId) || !neighbors.has(edge.targetId)) return;
    neighbors.get(edge.sourceId).add(edge.targetId);
    neighbors.get(edge.targetId).add(edge.sourceId);
  });
  return neighbors;
}

function associationComponents(neighbors) {
  const visited = new Set();
  const ids = [...neighbors.keys()].sort((a, b) => String(a).localeCompare(String(b)));
  const components = [];
  ids.forEach((id) => {
    if (visited.has(id)) return;
    const stack = [id];
    const component = [];
    visited.add(id);
    while (stack.length) {
      const current = stack.pop();
      component.push(current);
      const next = [...(neighbors.get(current) || [])].sort((a, b) => String(a).localeCompare(String(b)));
      next.forEach((n) => {
        if (visited.has(n)) return;
        visited.add(n);
        stack.push(n);
      });
    }
    components.push(component);
  });
  return components;
}

function layoutAssociationOnly(classes, assocEdges, rowStep) {
  const byId = new Map(classes.map((c) => [c.id, c]));
  const neighbors = buildAssociationNeighbors(classes, assocEdges);
  const components = associationComponents(neighbors);
  const nodes = [];
  let componentStartX = MARGIN_X;

  components.forEach((component) => {
    const sortedComponent = [...component].sort((a, b) => {
      const degreeDiff = (neighbors.get(b)?.size || 0) - (neighbors.get(a)?.size || 0);
      if (degreeDiff !== 0) return degreeDiff;
      return String(a).localeCompare(String(b));
    });
    const root = sortedComponent[0];
    if (!root) return;

    const dist = new Map([[root, 0]]);
    const queue = [root];
    while (queue.length) {
      const current = queue.shift();
      const currentDist = dist.get(current) ?? 0;
      const next = [...(neighbors.get(current) || [])].sort((a, b) => String(a).localeCompare(String(b)));
      next.forEach((n) => {
        if (dist.has(n)) return;
        dist.set(n, currentDist + 1);
        queue.push(n);
      });
    }

    const layers = new Map();
    sortedComponent.forEach((id) => {
      const level = dist.get(id) ?? 0;
      if (!layers.has(level)) layers.set(level, []);
      layers.get(level).push(id);
    });

    layers.forEach((ids, level) => {
      ids.sort((a, b) => {
        const degreeDiff = (neighbors.get(b)?.size || 0) - (neighbors.get(a)?.size || 0);
        if (degreeDiff !== 0) return degreeDiff;
        return String(a).localeCompare(String(b));
      });
      layers.set(level, ids);
    });

    const levelKeys = [...layers.keys()].sort((a, b) => a - b);
    const widest = Math.max(1, ...levelKeys.map((k) => (layers.get(k) || []).length));
    const componentWidth = widest * CLASS_WIDTH + Math.max(0, widest - 1) * X_GAP;

    levelKeys.forEach((level) => {
      const ids = layers.get(level) || [];
      const layerWidth = ids.length * CLASS_WIDTH + Math.max(0, ids.length - 1) * X_GAP;
      const layerStartX = componentStartX + (componentWidth - layerWidth) / 2;
      ids.forEach((id, index) => {
        const cls = byId.get(id);
        if (!cls) return;
        nodes.push({
          id: cls.id,
          className: cls.name,
          isAbstract: Boolean(cls.isAbstract),
          parent: cls.parent || null,
          attributes: cls.attributes || [],
          x: Math.round(layerStartX + index * (CLASS_WIDTH + X_GAP)),
          y: Math.round(MARGIN_Y + level * rowStep),
          width: CLASS_WIDTH,
          height: classNodeHeight(cls),
        });
      });
    });

    componentStartX += componentWidth + X_GAP * 2;
  });

  return nodes;
}

export function buildMetamodelGraph(metamodel) {
  if (!metamodel || !Array.isArray(metamodel.classes)) {
    return { name: "", nodes: [], edges: [] };
  }
  const classes = metamodel.classes;
  const inheritanceEdges = classes
    .filter((c) => c.parent)
    .map((c) => ({
      id: `inh_${c.id}_${c.parent}`,
      edgeType: "inheritance",
      sourceId: c.id,
      targetId: c.parent,
      label: "extends",
    }));

  const assocEdges = (metamodel.associations || []).map((a) => ({
    id: `assoc_${a.id}`,
    edgeType: Boolean(a.isContainment) === true ? "composition" : "reference",
    sourceId: a.sourceClass,
    targetId: a.targetClass,
    label: a.name,
    sourceMult: a.sourceMult,
    targetMult: a.targetMult,
  }));

  const { byId, children, roots } = buildInheritanceTree(classes);
  const subtreeWidths = new Map();
  function computeSubtreeWidths(id) {
    if (subtreeWidths.has(id)) return subtreeWidths.get(id);
    const w = subtreeWidth(id, children, byId);
    subtreeWidths.set(id, w);
    return w;
  }
  roots.forEach((id) => computeSubtreeWidths(id));

  const maxNodeHeight = Math.max(80, ...classes.map((c) => classNodeHeight(c)));
  const rowStep = maxNodeHeight + Y_GAP;
  let nodes = [];
  if (inheritanceEdges.length === 0) {
    nodes = layoutAssociationOnly(classes, assocEdges, rowStep);
  } else {
    nodes = [];
    let startX = MARGIN_X;
    roots.forEach((rootId) => {
      const w = subtreeWidths.get(rootId) ?? CLASS_WIDTH + X_GAP;
      placeNode(rootId, startX, startX + w, 0, byId, children, subtreeWidths, rowStep, nodes);
      startX += w + X_GAP;
    });
  }

  return {
    name: metamodel.name || "",
    nodes,
    edges: [...inheritanceEdges, ...assocEdges],
  };
}

