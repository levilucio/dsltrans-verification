let localId = 0;
function nextId() {
  localId += 1;
  return `edge_${localId}`;
}

function sanitizeMermaidId(id, fallbackIndex) {
  const normalized = String(id ?? "").replace(/[^a-zA-Z0-9_]/g, "_");
  if (!normalized) return `n_${fallbackIndex}`;
  return /^[a-zA-Z_]/.test(normalized) ? normalized : `n_${normalized}`;
}

function escapeMermaidText(value) {
  return String(value ?? "").replace(/"/g, '\\"');
}

/**
 * Extract the metamodel name (prefix) from the first object's xsi:type in XMI.
 * e.g. "Package:Package" -> "Package". Returns null if no objects or no type.
 */
export function getMetamodelNameFromXmi(xmiText) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xmiText, "application/xml");
  const first = doc.querySelector("objects");
  if (!first) return null;
  const type = first.getAttribute("xsi:type");
  if (!type || !type.includes(":")) return null;
  return type.split(":")[0];
}

/**
 * Validates that an input model can be loaded: a transformation must be loaded and
 * the model's metamodel must match the transformation's source metamodel.
 * @param {string} fileText - XMI content of the input model
 * @param {string | null | undefined} transformationSourceMetamodel - Source metamodel from loaded .dslt
 * @returns {{ ok: true } | { ok: false, error: string }}
 */
export function validateInputModelForTransformation(fileText, transformationSourceMetamodel) {
  if (transformationSourceMetamodel == null || transformationSourceMetamodel === "") {
    return {
      ok: false,
      error: "Load a transformation first (.dslt) to enable loading an input model.",
    };
  }
  const modelMetamodel = getMetamodelNameFromXmi(fileText);
  if (!modelMetamodel) {
    return {
      ok: false,
      error: "Could not determine metamodel from model (no objects or xsi:type).",
    };
  }
  if (modelMetamodel !== transformationSourceMetamodel) {
    return {
      ok: false,
      error: `Model metamodel "${modelMetamodel}" does not match the loaded transformation source metamodel "${transformationSourceMetamodel}".`,
    };
  }
  return { ok: true };
}

export function parseXmiToGraph(xmiText) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xmiText, "application/xml");
  const objects = [...doc.querySelectorAll("objects")].map((obj, idx) => ({
    id: obj.getAttribute("xmi:id") || obj.getAttribute("id") || `node_${idx}`,
    className: (obj.getAttribute("xsi:type") || "Unknown:Node").split(":").pop(),
    attrs: [...obj.attributes].reduce((acc, attr) => {
      if (!["xmi:id", "id", "xsi:type"].includes(attr.name)) acc[attr.name] = attr.value;
      return acc;
    }, {}),
  }));

  const links = [...doc.querySelectorAll("links")].map((link) => ({
    id: nextId(),
    sourceId: link.getAttribute("source"),
    targetId: link.getAttribute("target"),
    assocName: (link.getAttribute("xsi:type") || "unknown").split(":").pop(),
    edgeType: "association",
  }));

  const traces = [...doc.querySelectorAll("traces")].map((trace) => ({
    id: nextId(),
    sourceId: trace.getAttribute("source"),
    targetId: trace.getAttribute("target"),
    assocName: "trace",
    edgeType: "trace",
  }));

  return { nodes: objects, edges: [...links, ...traces] };
}

export function stringifyGraphToXmi(graph, metamodelName = "Model") {
  const objectLines = graph.nodes.map((node) => {
    const attrs = Object.entries(node.attrs || {})
      .map(([k, v]) => `${k}="${String(v)}"`)
      .join(" ");
    const attrsPart = attrs ? ` ${attrs}` : "";
    return `  <objects xmi:id="${node.id}" xsi:type="${metamodelName}:${node.className}"${attrsPart} />`;
  });

  const edgeLines = graph.edges
    .filter((edge) => edge.edgeType !== "trace")
    .map(
      (edge) =>
        `  <links xsi:type="${metamodelName}:${edge.assocName || "link"}" source="${edge.sourceId}" target="${edge.targetId}" />`,
    );

  const traceLines = graph.edges
    .filter((edge) => edge.edgeType === "trace")
    .map((edge) => `  <traces source="${edge.sourceId}" target="${edge.targetId}" />`);

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
    ...objectLines,
    ...edgeLines,
    ...traceLines,
    "</model>",
  ].join("\n");
}

export function stringifyGraphToMermaid(graph, title = "Model") {
  const idMap = new Map(
    (graph.nodes || []).map((node, idx) => [node.id, sanitizeMermaidId(node.id, idx)]),
  );

  const nodeLines = (graph.nodes || []).map((node, idx) => {
    const nodeId = idMap.get(node.id) || sanitizeMermaidId(node.id, idx);
    const nodeLabel = `${node.className}\\n${node.id}`;
    const escaped = escapeMermaidText(nodeLabel);
    if (String(node.className).toLowerCase().includes("place")) return `  ${nodeId}(("${escaped}"))`;
    if (
      String(node.className).toLowerCase().includes("gateway") ||
      String(node.className).toLowerCase().includes("decision")
    ) {
      return `  ${nodeId}{"${escaped}"}`;
    }
    return `  ${nodeId}["${escaped}"]`;
  });

  const edgeLines = (graph.edges || [])
    .filter((edge) => idMap.has(edge.sourceId) && idMap.has(edge.targetId))
    .map((edge) => {
      const src = idMap.get(edge.sourceId);
      const tgt = idMap.get(edge.targetId);
      const label = escapeMermaidText(edge.assocName || (edge.edgeType === "trace" ? "trace" : "link"));
      const arrow = edge.edgeType === "trace" ? "-.->" : "-->";
      return `  ${src} ${arrow}|${label}| ${tgt}`;
    });

  return ["flowchart LR", `  %% ${title}`, ...nodeLines, ...edgeLines].join("\n");
}

const UML_CLASSIFIER_KINDS = new Set(["Class", "Interface", "Enumeration"]);

/**
 * True when the metamodel name indicates a UML model (e.g. UML, UMLConcrete).
 */
export function isUmlMetamodel(name) {
  if (name == null || typeof name !== "string") return false;
  const n = name.trim();
  if (!n) return false;
  return n === "UML" || n === "UMLConcrete" || n.toLowerCase().startsWith("uml");
}

/**
 * Activity metamodel from DSLTrans fragments (e.g. UseCase2Activity target).
 */
export function isActivityMetamodel(name) {
  if (name == null || typeof name !== "string") return false;
  return name.trim() === "Activity";
}

/**
 * Parse compact Activity XMI into actions and flow transitions (src/dst on Flow objects).
 * @returns {{ actions: Array<{id, label}>, transitions: Array<{fromId, toId, flowId}> }}
 */
export function parseXmiToActivityFlowStructure(xmiText) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xmiText, "application/xml");
  const objects = Object.create(null);
  for (const obj of doc.querySelectorAll("objects")) {
    const id = obj.getAttribute("xmi:id") || obj.getAttribute("id");
    if (!id) continue;
    const type = obj.getAttribute("xsi:type") || "";
    const className = type.includes(":") ? type.split(":").pop() : type;
    const name = obj.getAttribute("name") || "";
    objects[id] = { id, className, name };
  }

  const outLinks = buildOutLinks(doc);
  const actions = [];
  const transitions = [];

  for (const obj of Object.values(objects)) {
    if (obj.className !== "ActivityModel") continue;
    const actionIds = outLinks[obj.id]?.nodes ?? [];
    for (const aid of actionIds) {
      const a = objects[aid];
      if (!a || a.className !== "Action") continue;
      const label = a.name ? `${a.name}\\n${a.id}` : `Action\\n${a.id}`;
      actions.push({ id: a.id, label });
    }
    const flowIds = outLinks[obj.id]?.edges ?? [];
    for (const fid of flowIds) {
      const flow = objects[fid];
      if (!flow || flow.className !== "Flow") continue;
      const srcList = outLinks[fid]?.src ?? [];
      const dstList = outLinks[fid]?.dst ?? [];
      const fromId = srcList[0];
      const toId = dstList[0];
      if (fromId && toId) transitions.push({ fromId, toId, flowId: fid });
    }
  }

  return { actions, transitions };
}

/**
 * Mermaid flowchart TD for Activity models (actions as nodes, flows as arrows).
 */
export function stringifyActivityFlowToMermaid(structure, title = "Activity") {
  const { actions, transitions } = structure;
  const idMap = new Map(actions.map((a, idx) => [a.id, sanitizeMermaidId(a.id, idx)]));
  const lines = ["flowchart TD", `  %% ${title}`];
  for (let i = 0; i < actions.length; i += 1) {
    const a = actions[i];
    const mid = idMap.get(a.id) || sanitizeMermaidId(a.id, i);
    lines.push(`  ${mid}["${escapeMermaidText(a.label)}"]`);
  }
  for (const t of transitions) {
    const src = idMap.get(t.fromId);
    const tgt = idMap.get(t.toId);
    if (!src || !tgt) continue;
    const lab = escapeMermaidText(t.flowId || "flow");
    lines.push(`  ${src} -->|${lab}| ${tgt}`);
  }
  return lines.join("\n");
}

/**
 * Build outLinks: for each object id, map association name -> list of target ids.
 */
function buildOutLinks(doc) {
  const outLinks = Object.create(null);
  for (const link of doc.querySelectorAll("links")) {
    const source = link.getAttribute("source");
    const target = link.getAttribute("target");
    const assocName = (link.getAttribute("xsi:type") || "").split(":").pop();
    if (!source || !target || !assocName) continue;
    if (!outLinks[source]) outLinks[source] = Object.create(null);
    if (!outLinks[source][assocName]) outLinks[source][assocName] = [];
    outLinks[source][assocName].push(target);
  }
  return outLinks;
}

/**
 * Parse XMI into a UML-oriented structure for class diagram generation.
 * Expects UML-style objects (Class, Interface, Enumeration, Property, Operation, etc.) and links.
 * @returns {{ classifiers: Array<{id, name, kind, attributes, operations, literals}>, generalizations: Array<{parentId, childId}>, realizations: Array<{classId, interfaceId}>, dependencies: Array<{clientId, supplierId}> }}
 */
export function parseXmiToUmlStructure(xmiText) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xmiText, "application/xml");
  const objects = Object.create(null);
  for (const obj of doc.querySelectorAll("objects")) {
    const id = obj.getAttribute("xmi:id") || obj.getAttribute("id");
    if (!id) continue;
    const type = obj.getAttribute("xsi:type");
    const className = type && type.includes(":") ? type.split(":").pop() : "Unknown";
    const attrs = {};
    for (const a of obj.attributes) {
      if (a.name !== "xmi:id" && a.name !== "id" && a.name !== "xsi:type" && !a.name.startsWith("{")) {
        attrs[a.name] = a.value;
      }
    }
    objects[id] = { id, className, attrs };
  }
  const outLinks = buildOutLinks(doc);

  const classifiers = [];
  for (const obj of Object.values(objects)) {
    if (!UML_CLASSIFIER_KINDS.has(obj.className)) continue;
    const name = obj.attrs.name ?? obj.id;
    const attrs = [];
    for (const propId of outLinks[obj.id]?.ownedAttribute ?? []) {
      const prop = objects[propId];
      if (!prop) continue;
      const propName = prop.attrs.name ?? propId;
      const typeIds = outLinks[propId]?.type ?? [];
      const typeName = typeIds.length && objects[typeIds[0]] ? (objects[typeIds[0]].attrs.name ?? typeIds[0]) : "";
      attrs.push({ name: propName, typeName });
    }
    const operations = [];
    const opIds = [
      ...(outLinks[obj.id]?.ownedOperation ?? []),
      ...(outLinks[obj.id]?.interfaceOperation ?? []),
    ];
    for (const opId of opIds) {
      const op = objects[opId];
      if (!op) continue;
      const opName = op.attrs.name ?? opId;
      const paramIds = outLinks[opId]?.ownedParameter ?? [];
      const params = paramIds.map((pid) => {
        const typeIds = outLinks[pid]?.paramType ?? [];
        const t = typeIds.length && objects[typeIds[0]] ? objects[typeIds[0]].attrs.name : "";
        return { typeName: t };
      });
      const retIds = outLinks[opId]?.returnType ?? [];
      const returnTypeName =
        retIds.length && objects[retIds[0]] ? (objects[retIds[0]].attrs.name ?? objects[retIds[0]].className) : "";
      operations.push({ name: opName, params, returnTypeName });
    }
    const literals = [];
    if (obj.className === "Enumeration") {
      for (const litId of outLinks[obj.id]?.ownedLiteral ?? []) {
        const lit = objects[litId];
        literals.push(lit?.attrs?.name ?? litId);
      }
    }
    classifiers.push({
      id: obj.id,
      name,
      kind: obj.className,
      attributes: attrs,
      operations,
      literals,
    });
  }

  const generalizations = [];
  for (const obj of Object.values(objects)) {
    if (obj.className !== "Generalization") continue;
    const general = outLinks[obj.id]?.general ?? [];
    const specific = outLinks[obj.id]?.specific ?? [];
    if (general.length && specific.length) {
      generalizations.push({ parentId: general[0], childId: specific[0] });
    }
  }

  const realizations = [];
  for (const obj of Object.values(objects)) {
    if (obj.className !== "InterfaceRealization") continue;
    const contract = outLinks[obj.id]?.contract ?? [];
    const implementingClass = outLinks[obj.id]?.implementingClass ?? [];
    if (contract.length && implementingClass.length) {
      realizations.push({ interfaceId: contract[0], classId: implementingClass[0] });
    }
  }

  const dependencies = [];
  for (const obj of Object.values(objects)) {
    if (!["Dependency", "Usage", "Realization"].includes(obj.className)) continue;
    const client = outLinks[obj.id]?.client ?? [];
    const supplier = outLinks[obj.id]?.supplier ?? [];
    if (client.length && supplier.length) {
      dependencies.push({ clientId: client[0], supplierId: supplier[0] });
    }
  }

  return { classifiers, generalizations, realizations, dependencies, objects };
}

/**
 * Sanitize a class name for Mermaid: safe for use as identifier (no spaces unless quoted).
 */
function mermaidClassLabel(name) {
  const s = String(name ?? "").trim();
  if (!s) return "Unnamed";
  if (/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(s)) return s;
  return `"${s.replace(/"/g, '\\"')}"`;
}

/**
 * Turn a UML structure from parseXmiToUmlStructure into a Mermaid classDiagram string.
 */
export function stringifyUmlToMermaidClassDiagram(umlStructure, title = "UML Model") {
  const { classifiers, generalizations, realizations, dependencies, objects } = umlStructure;
  const idToLabel = new Map();
  const used = new Set();
  for (const c of classifiers) {
    let label = mermaidClassLabel(c.name);
    if (used.has(label)) label = mermaidClassLabel(c.name + "_" + c.id);
    used.add(label);
    idToLabel.set(c.id, label);
  }

  const lines = ["classDiagram", `  %% ${title}`];

  for (const c of classifiers) {
    const label = idToLabel.get(c.id);
    if (!label) continue;
    if (c.kind === "Interface") {
      lines.push(`  class ${label} { <<interface>> }`);
    } else if (c.kind === "Enumeration" && c.literals.length > 0) {
      lines.push(`  class ${label} {`);
      for (const lit of c.literals) lines.push(`    ${mermaidClassLabel(lit)}`);
      lines.push("  }");
    } else if (c.attributes.length > 0 || c.operations.length > 0) {
      lines.push(`  class ${label} {`);
      for (const a of c.attributes) {
        const typePart = a.typeName ? ` ${a.typeName}` : "";
        lines.push(`    +${a.name}${typePart}`);
      }
      for (const op of c.operations) {
        const params = op.params.map((p) => p.typeName || "").join(", ");
        const ret = op.returnTypeName ? ` ${op.returnTypeName}` : "";
        lines.push(`    +${op.name}(${params})${ret}`);
      }
      lines.push("  }");
    } else {
      lines.push(`  class ${label}`);
    }
  }

  const classifierIds = new Set(classifiers.map((c) => c.id));
  const addRel = (fromId, toId, arrow, label) => {
    const fromL = idToLabel.get(fromId);
    const toL = idToLabel.get(toId);
    if (fromL && toL && classifierIds.has(fromId) && classifierIds.has(toId)) {
      lines.push(`  ${fromL} ${arrow} ${toL}${label ? ` : ${label}` : ""}`);
    }
  };

  for (const { parentId, childId } of generalizations) {
    addRel(parentId, childId, "<|--", "");
  }
  for (const { classId, interfaceId } of realizations) {
    addRel(interfaceId, classId, "<|..", "implements");
  }
  for (const { clientId, supplierId } of dependencies) {
    addRel(supplierId, clientId, "..>", "uses");
  }

  return lines.join("\n");
}

/**
 * Return Mermaid string for the model: Activity TD, UML class diagram, or generic flowchart.
 * @param {string | null | undefined} metamodelHint - source metamodel for input panel, or target for output when passed via ModelPanel
 */
export function getMermaidForModel(graph, text, title, metamodelHint) {
  if (isActivityMetamodel(metamodelHint) && text) {
    try {
      const act = parseXmiToActivityFlowStructure(text);
      if (act.actions.length > 0 || act.transitions.length > 0) {
        return stringifyActivityFlowToMermaid(act, title);
      }
    } catch (_) {
      // fallback below
    }
  }
  if (isUmlMetamodel(metamodelHint) && text) {
    try {
      const uml = parseXmiToUmlStructure(text);
      if (uml.classifiers.length > 0) {
        return stringifyUmlToMermaidClassDiagram(uml, title);
      }
    } catch (_) {
      // fallback to generic flowchart on parse error
    }
  }
  return stringifyGraphToMermaid(graph, title);
}
