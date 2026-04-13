export function autoLayoutNodes(nodes, width = 1400) {
  const byClass = nodes.reduce((acc, node) => {
    const key = node.className || node.kind || "Node";
    if (!acc[key]) acc[key] = [];
    acc[key].push(node);
    return acc;
  }, {});

  const classes = Object.keys(byClass).sort();
  const laneWidth = Math.max(220, Math.floor(width / Math.max(classes.length, 1)));
  const baseY = 80;

  return nodes.map((node) => {
    const classIdx = classes.findIndex((c) => c === (node.className || node.kind || "Node"));
    const sameClassNodes = byClass[node.className || node.kind || "Node"];
    const index = sameClassNodes.findIndex((n) => n.id === node.id);
    return {
      ...node,
      x: classIdx * laneWidth + 80,
      y: baseY + index * 100,
    };
  });
}
