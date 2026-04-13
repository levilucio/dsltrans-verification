import { NODE_KINDS } from "@/utils/dsltransModel";

const HEADER = "dsltransformation";

function makeId(prefix, idx) {
  return `${prefix}_${idx}`;
}

function pickLayout(existingDoc, key, fallbackX, fallbackY) {
  if (!existingDoc?._layoutIndex?.[key]) {
    return { x: fallbackX, y: fallbackY };
  }
  return existingDoc._layoutIndex[key];
}

/** Extract variable name from element label, e.g. "any pn: PhysicalNode" -> "pn", "sysMap : SystemMapping" -> "sysMap" */
function varNameFromLabel(label) {
  const s = label.trim();
  const beforeColon = s.includes(":") ? s.split(":")[0].trim() : s;
  const m = beforeColon.match(/^any\s+(\S+)$/);
  return m ? m[1] : beforeColon.split(/\s+/)[0] || beforeColon;
}

/**
 * Parse match element label into structured data.
 * e.g. "any cls : Class where cls.isAbstract == true" -> { matchType, varName, className, whereClause }
 * Falls back to "varName : ClassName" for legacy labels.
 */
function parseMatchElementLabel(label) {
  if (!label || typeof label !== "string") return null;
  const s = label.trim();
  const full = s.match(/^(any|exists)\s+(\w+)\s*:\s*(\S+)(?:\s+where\s+(.+))?$/i);
  if (full)
    return {
      matchType: full[1].toLowerCase(),
      varName: full[2],
      className: full[3].trim(),
      whereClause: full[4]?.trim() || null,
    };
  const minimal = s.match(/^\s*(\w+)\s*:\s*(\S+)\s*$/);
  if (minimal)
    return {
      matchType: "any",
      varName: minimal[1],
      className: minimal[2].trim(),
      whereClause: null,
    };
  return null;
}

/**
 * Parse apply element line (may include { attr = expr, ... }) into structured data.
 * Falls back to "varName : ClassName" for legacy labels.
 */
function parseApplyElementLabel(line) {
  if (!line || typeof line !== "string") return null;
  const idx = line.indexOf("{");
  if (idx === -1) {
    const m = line.trim().match(/^\s*(\w+)\s*:\s*(\S+)\s*$/);
    return m ? { varName: m[1], className: m[2].trim(), attributeBindings: [] } : null;
  }
  const end = line.indexOf("}", idx);
  if (end === -1) return null;
  const before = line.substring(0, idx).trim();
  const content = line.substring(idx + 1, end).trim();
  const m = before.match(/^\s*(\w+)\s*:\s*(\S+)\s*$/);
  if (!m) return null;
  const bindings = [];
  if (content) {
    const parts = content.split(",").map((p) => p.trim()).filter(Boolean);
    for (const part of parts) {
      const eq = part.indexOf("=");
      if (eq === -1) continue;
      bindings.push({
        attr: part.substring(0, eq).trim(),
        expr: part.substring(eq + 1).trim(),
      });
    }
  }
  return { varName: m[1], className: m[2].trim(), attributeBindings: bindings };
}

export function buildMatchLine(node) {
  if (node.matchType != null && node.varName != null && node.className != null) {
    const base = `${node.matchType} ${node.varName} : ${node.className}`;
    return node.whereClause ? `${base} where ${node.whereClause}` : base;
  }
  return node.label;
}

export function buildApplyLine(node) {
  if (node.varName != null && node.className != null && node.attributeBindings?.length > 0) {
    const bindings = node.attributeBindings.map((b) => `${b.attr} = ${b.expr}`).join(", ");
    return `${node.varName} : ${node.className} { ${bindings} }`;
  }
  if (node.varName != null && node.className != null) {
    return `${node.varName} : ${node.className}`;
  }
  return node.label;
}

/**
 * Parse relation declaration lines such as:
 * - "direct rel : assoc -- a.b"
 * - "hasLink : has -- c.woman"
 */
function parseRelationDeclaration(line) {
  const m = line.match(
    /^(?:direct\s+)?([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)\s*--\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*$/,
  );
  if (!m) return null;
  return {
    relationVar: m[1],
    assocName: m[2],
    sourceVar: m[3],
    targetVar: m[4],
  };
}

export function serializeDsltrans(doc) {
  const lines = [HEADER, ""];
  const layers = [...doc.layers].sort((a, b) => a.index - b.index);
  for (const layer of layers) {
    lines.push(`layer ${layer.name} {`);
    const rules = doc.nodes
      .filter((n) => n.kind === NODE_KINDS.RULE && n.layerId === layer.id)
      .sort((a, b) => a.y - b.y || a.x - b.x);
    for (const rule of rules) {
      lines.push(`  rule ${rule.label} {`);
      const match = doc.nodes
        .filter((n) => n.parentRuleId === rule.id && n.kind === NODE_KINDS.MATCH)
        .sort((a, b) => a.y - b.y || a.x - b.x);
      const apply = doc.nodes
        .filter((n) => n.parentRuleId === rule.id && n.kind === NODE_KINDS.APPLY)
        .sort((a, b) => a.y - b.y || a.x - b.x);
      lines.push("    match {");
      match.forEach((m) => lines.push(`      ${buildMatchLine(m)}`));
      lines.push("    }");
      lines.push("    apply {");
      apply.forEach((a) => lines.push(`      ${buildApplyLine(a)}`));
      lines.push("    }");
      lines.push("  }");
    }
    lines.push("}");
    lines.push("");
  }
  return lines.join("\n");
}

export function parseDsltransToGraph(text, existingDoc = null) {
  const clean = text.replace(/\r\n/g, "\n");
  const lines = clean.split("\n");
  if (!lines.some((l) => l.includes("transformation") || l.includes("dsltransformation"))) {
    throw new Error("Not a DSLTrans-like document");
  }

  const layers = [];
  const nodes = [];
  const edges = [];
  const pendingSectionEdges = [];
  const parsedRules = [];
  const stack = [];
  let currentLayer = null;
  let currentRule = null;
  let currentSection = null;
  let layerCounter = 0;
  let ruleCounter = 0;
  let elementCounter = 0;
  let edgeCounter = 0;
  /** When in match/apply section, depth of inline { } so we don't close the section on inner } */
  let inlineBraceDepth = 0;

  for (let i = 0; i < lines.length; i += 1) {
    const raw = lines[i];
    const line = raw.trim();
    if (!line || line.startsWith("//")) continue;

    const layerMatch = line.match(/^layer\s+([A-Za-z0-9_]+)\s*\{$/);
    if (layerMatch) {
      const layerName = layerMatch[1];
      const layerId = makeId("layer", layerCounter + 1);
      const layout = pickLayout(existingDoc, `layer:${layerName}`, 100 + layerCounter * 320, 100);
      layers.push({ id: layerId, name: layerName, index: layerCounter, x: layout.x, y: layout.y });
      layerCounter += 1;
      currentLayer = layers[layers.length - 1];
      stack.push("layer");
      continue;
    }

    const ruleMatch = line.match(/^rule\s+([A-Za-z0-9_]+)\s*\{$/);
    if (ruleMatch && currentLayer) {
      const ruleName = ruleMatch[1];
      const ruleId = makeId("rule", ruleCounter + 1);
      const layerRulesCount = parsedRules.filter((r) => r.layerId === currentLayer.id).length;
      const layout = pickLayout(
        existingDoc,
        `rule:${currentLayer.name}:${ruleName}`,
        100 + currentLayer.index * 320,
        100 + layerRulesCount * 220,
      );
      const ruleNode = {
        id: ruleId,
        kind: NODE_KINDS.RULE,
        label: ruleName,
        x: layout.x,
        y: layout.y,
        width: 260,
        height: 180,
        layerId: currentLayer.id,
      };
      nodes.push(ruleNode);
      parsedRules.push({ ...ruleNode });
      currentRule = ruleNode;
      ruleCounter += 1;
      stack.push("rule");
      continue;
    }

    const matchInline = line.match(/^match\s*\{\s*(.*)\}\s*$/);
    if (matchInline && currentRule) {
      currentSection = NODE_KINDS.MATCH;
      const content = matchInline[1].trim();
      if (content) {
        const parts = content.split(",").map((p) => p.trim()).filter(Boolean);
        parts.forEach((partLabel, idx) => {
          elementCounter += 1;
          const sameSectionCount = nodes.filter(
            (n) => n.parentRuleId === currentRule.id && n.kind === NODE_KINDS.MATCH,
          ).length + idx;
          const defaultX = currentRule.x + 25;
          const defaultY = currentRule.y + 35 + sameSectionCount * 40;
          const layout = pickLayout(
            existingDoc,
            `element:${currentRule.label}:${NODE_KINDS.MATCH}:${partLabel}`,
            defaultX,
            defaultY,
          );
          const parsed = parseMatchElementLabel(partLabel);
          nodes.push({
            id: makeId("element", elementCounter),
            kind: NODE_KINDS.MATCH,
            label: partLabel,
            x: layout.x,
            y: layout.y,
            width: 140,
            height: 60,
            parentRuleId: currentRule.id,
            layerId: currentRule.layerId,
            ...(parsed || {}),
          });
        });
      }
      continue;
    }

    const applyInline = line.match(/^apply\s*\{\s*(.*)\}\s*$/);
    if (applyInline && currentRule) {
      currentSection = NODE_KINDS.APPLY;
      const content = applyInline[1].trim();
      if (content) {
        const parts = content.split(",").map((p) => p.trim()).filter(Boolean);
        parts.forEach((partLabel, idx) => {
          elementCounter += 1;
          const sameSectionCount = nodes.filter(
            (n) => n.parentRuleId === currentRule.id && n.kind === NODE_KINDS.APPLY,
          ).length + idx;
          const defaultX = currentRule.x + 145;
          const defaultY = currentRule.y + 35 + sameSectionCount * 40;
          const layout = pickLayout(
            existingDoc,
            `element:${currentRule.label}:${NODE_KINDS.APPLY}:${partLabel}`,
            defaultX,
            defaultY,
          );
          const parsed = parseApplyElementLabel(partLabel);
          nodes.push({
            id: makeId("element", elementCounter),
            kind: NODE_KINDS.APPLY,
            label: partLabel,
            x: layout.x,
            y: layout.y,
            width: 140,
            height: 60,
            parentRuleId: currentRule.id,
            layerId: currentRule.layerId,
            ...(parsed || {}),
          });
        });
      }
      continue;
    }

    if (line === "match {" && currentRule) {
      currentSection = NODE_KINDS.MATCH;
      inlineBraceDepth = 0;
      stack.push("match");
      continue;
    }

    if (line === "apply {" && currentRule) {
      currentSection = NODE_KINDS.APPLY;
      inlineBraceDepth = 0;
      stack.push("apply");
      continue;
    }

    const backwardInline = line.match(/^backward\s*\{\s*(.*)\}\s*$/);
    if (backwardInline && currentRule) {
      const content = backwardInline[1].trim();
      if (content) {
        const traceLines = content.split(",").map((s) => s.trim()).filter(Boolean);
        traceLines.forEach((traceLine) => {
          const traceMatch = traceLine.match(/^(.+?)\s*<--trace--\s*(.+)$/);
          if (traceMatch) {
            const applyVar = traceMatch[1].trim().split(/\s+/)[0];
            const matchVar = traceMatch[2].trim().split(/\s+/)[0];
            const ruleMatchNodes = nodes.filter(
              (n) => n.parentRuleId === currentRule.id && n.kind === NODE_KINDS.MATCH,
            );
            const ruleApplyNodes = nodes.filter(
              (n) => n.parentRuleId === currentRule.id && n.kind === NODE_KINDS.APPLY,
            );
            const matchNode = ruleMatchNodes.find((n) => varNameFromLabel(n.label) === matchVar);
            const applyNode = ruleApplyNodes.find((n) => varNameFromLabel(n.label) === applyVar);
            if (matchNode && applyNode) {
              edgeCounter += 1;
              edges.push({
                id: makeId("edge", edgeCounter),
                sourceId: matchNode.id,
                targetId: applyNode.id,
                edgeType: "trace",
              });
            }
          }
        });
      }
      continue;
    }

    if (line === "backward {" && currentRule) {
      currentSection = "backward";
      inlineBraceDepth = 0;
      stack.push("backward");
      continue;
    }

    if (line === "}") {
      if (
        (currentSection === NODE_KINDS.MATCH || currentSection === NODE_KINDS.APPLY) &&
        inlineBraceDepth > 0
      ) {
        inlineBraceDepth -= 1;
        continue;
      }
      if (
        (currentSection === NODE_KINDS.MATCH || currentSection === NODE_KINDS.APPLY) &&
        inlineBraceDepth === 0
      ) {
        inlineBraceDepth = 0;
      }
      const top = stack.pop();
      if (top === "match" || top === "apply" || top === "backward") currentSection = null;
      if (top === "rule") currentRule = null;
      if (top === "layer") currentLayer = null;
      continue;
    }

    if (currentRule && currentSection === "backward") {
      const traceMatch = line.match(/^(.+?)\s*<--trace--\s*(.+)$/);
      if (traceMatch) {
        const applyVar = traceMatch[1].trim().split(/\s+/)[0];
        const matchVar = traceMatch[2].trim().split(/\s+/)[0];
        const ruleMatchNodes = nodes.filter(
          (n) => n.parentRuleId === currentRule.id && n.kind === NODE_KINDS.MATCH,
        );
        const ruleApplyNodes = nodes.filter(
          (n) => n.parentRuleId === currentRule.id && n.kind === NODE_KINDS.APPLY,
        );
        const matchNode = ruleMatchNodes.find((n) => varNameFromLabel(n.label) === matchVar);
        const applyNode = ruleApplyNodes.find((n) => varNameFromLabel(n.label) === applyVar);
        if (matchNode && applyNode) {
          edgeCounter += 1;
          edges.push({
            id: makeId("edge", edgeCounter),
            sourceId: matchNode.id,
            targetId: applyNode.id,
            edgeType: "trace",
          });
        }
      }
      continue;
    }

    if (
      currentRule &&
      (currentSection === NODE_KINDS.MATCH || currentSection === NODE_KINDS.APPLY) &&
      inlineBraceDepth === 0
    ) {
      const hasInlineBraces = line.includes("{");
      const label = hasInlineBraces
        ? line.substring(0, line.indexOf("{")).trim()
        : line;
      const relation = parseRelationDeclaration(label);
      if (relation) {
        pendingSectionEdges.push({
          ruleId: currentRule.id,
          section: currentSection,
          sourceVar: relation.sourceVar,
          targetVar: relation.targetVar,
          // Display metamodel association name in the graph (e.g. "root"), not relation variable aliases.
          label: relation.assocName || relation.relationVar,
        });
        if (hasInlineBraces) {
          const open = (line.match(/{/g) || []).length;
          const close = (line.match(/}/g) || []).length;
          inlineBraceDepth += open - close;
        }
        continue;
      }
      if (!label) {
        if (hasInlineBraces) {
          const open = (line.match(/{/g) || []).length;
          const close = (line.match(/}/g) || []).length;
          inlineBraceDepth += open - close;
        }
        continue;
      }
      elementCounter += 1;
      const sameSectionCount = nodes.filter(
        (n) => n.parentRuleId === currentRule.id && n.kind === currentSection,
      ).length;
      const defaultX =
        currentSection === NODE_KINDS.MATCH ? currentRule.x + 25 : currentRule.x + 145;
      const defaultY = currentRule.y + 35 + sameSectionCount * 40;
      const fullLine = line;
      const layout = pickLayout(
        existingDoc,
        `element:${currentRule.label}:${currentSection}:${fullLine.trim()}`,
        defaultX,
        defaultY,
      );
      const parsed =
        currentSection === NODE_KINDS.MATCH
          ? parseMatchElementLabel(label)
          : parseApplyElementLabel(hasInlineBraces ? fullLine : label);
      nodes.push({
        id: makeId("element", elementCounter),
        kind: currentSection,
        label: fullLine.trim(),
        x: layout.x,
        y: layout.y,
        width: 140,
        height: 60,
        parentRuleId: currentRule.id,
        layerId: currentRule.layerId,
        ...(parsed || {}),
      });
      if (hasInlineBraces) {
        const open = (line.match(/{/g) || []).length;
        const close = (line.match(/}/g) || []).length;
        inlineBraceDepth += open - close;
      }
    }
  }

  pendingSectionEdges.forEach((edge) => {
    const sectionNodes = nodes.filter(
      (n) => n.parentRuleId === edge.ruleId && n.kind === edge.section,
    );
    const src = sectionNodes.find(
      (n) => varNameFromLabel(n.label) === edge.sourceVar,
    );
    const tgt = sectionNodes.find(
      (n) => varNameFromLabel(n.label) === edge.targetVar,
    );
    if (!src || !tgt) return;
    edgeCounter += 1;
    edges.push({
      id: makeId("edge", edgeCounter),
      sourceId: src.id,
      targetId: tgt.id,
      edgeType: "direct",
      label: edge.label,
    });
  });

  return { layers, nodes, edges };
}

export function parseDsltrans(text) {
  const graph = parseDsltransToGraph(text);
  const rules = graph.nodes.filter((n) => n.kind === NODE_KINDS.RULE);
  return { layers: graph.layers, rules };
}

export function buildLayoutIndex(doc) {
  const index = {};
  doc.layers.forEach((layer) => {
    index[`layer:${layer.name}`] = { x: layer.x ?? 100 + layer.index * 320, y: layer.y ?? 100 };
  });
  doc.nodes
    .filter((n) => n.kind === NODE_KINDS.RULE)
    .forEach((rule) => {
      const layer = doc.layers.find((l) => l.id === rule.layerId);
      if (!layer) return;
      index[`rule:${layer.name}:${rule.label}`] = { x: rule.x, y: rule.y };
    });
  doc.nodes
    .filter((n) => n.parentRuleId && (n.kind === NODE_KINDS.MATCH || n.kind === NODE_KINDS.APPLY))
    .forEach((node) => {
      const parentRule = doc.nodes.find((r) => r.id === node.parentRuleId);
      if (!parentRule) return;
      index[`element:${parentRule.label}:${node.kind}:${node.label}`] = { x: node.x, y: node.y };
    });
  return index;
}

/**
 * Extract content of a single {...} block starting at index start in string s.
 * Returns { content, endIndex } or null.
 */
function extractBlock(s, start) {
  const open = s.indexOf("{", start);
  if (open === -1) return null;
  let depth = 1;
  for (let k = open + 1; k < s.length; k++) {
    if (s[k] === "{") depth++;
    else if (s[k] === "}") {
      depth--;
      if (depth === 0) return { content: s.slice(open + 1, k).trim(), endIndex: k + 1 };
    }
  }
  return null;
}

/**
 * Parse transformation properties from DSLTrans spec text.
 * Returns [{ name, description, precondition, postcondition }]
 * where description is optional and pre/post are trimmed block contents.
 */
export function parsePropertiesFromSpec(specText) {
  if (!specText || typeof specText !== "string") return [];
  const properties = [];
  const re = /property\s+([A-Za-z0-9_]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\{/g;
  let m;
  while ((m = re.exec(specText)) !== null) {
    const name = m[1];
    const description = m[2] ? m[2].replace(/\\"/g, '"') : "";
    const block = extractBlock(specText, m.index + m[0].length - 1);
    if (!block) continue;
    const inner = block.content;
    let precondition = "";
    let postcondition = "";
    const preMatch = inner.match(/precondition\s*\{/);
    if (preMatch) {
      const preBlock = extractBlock(inner, inner.indexOf("{", preMatch.index));
      if (preBlock) precondition = preBlock.content;
    }
    const postMatch = inner.match(/postcondition\s*\{/);
    if (postMatch) {
      const postBlock = extractBlock(inner, inner.indexOf("{", postMatch.index));
      if (postBlock) postcondition = postBlock.content;
    }
    properties.push({ name, description, precondition, postcondition });
  }
  return properties;
}

function tokenizePrecondition(content) {
  const tokens = [];
  const s = (content || "").replace(/\s+/g, " ").trim();
  let rest = s;

  while (rest) {
    rest = rest.trim();
    if (!rest) break;

    const rel = rest.match(
      /^(direct\s+[A-Za-z_]\w*\s*:\s*[A-Za-z_]\w*\s*--\s*[A-Za-z_]\w*\.[A-Za-z_]\w*)(?=\s+(?:direct\s+[A-Za-z_]\w*\s*:|(?:any|exists)\s+\w+\s*:)|$)/,
    );
    if (rel) {
      tokens.push(rel[1].trim());
      rest = rest.slice(rel[0].length);
      continue;
    }

    const elem = rest.match(
      /^(?:any|exists)\s+\w+\s*:\s*\S+(?:\s+where\s+.*?(?=\s+direct\s+[A-Za-z_]\w*\s*:|\s+(?:any|exists)\s+\w+\s*:|$))?/,
    );
    if (elem) {
      tokens.push(elem[0].trim());
      rest = rest.slice(elem[0].length);
      continue;
    }

    break;
  }

  return tokens;
}

function tokenizePostcondition(content) {
  const tokens = [];
  const s = (content || "").replace(/\s+/g, " ").trim();
  let rest = s;

  while (rest) {
    rest = rest.trim();
    if (!rest) break;

    const trace = rest.match(/^([A-Za-z_]\w*\s*<--trace--\s*[A-Za-z_]\w*)/);
    if (trace) {
      tokens.push(trace[1].trim());
      rest = rest.slice(trace[0].length);
      continue;
    }

    const rel = rest.match(
      /^([A-Za-z_]\w*\s*:\s*[A-Za-z_]\w*\s*--\s*[A-Za-z_]\w*\.[A-Za-z_]\w*)(?=\s+[A-Za-z_]\w*\s*<--trace--|\s+(?:direct\s+)?[A-Za-z_]\w*\s*:\s*[A-Za-z_]\w*\s*--|\s+[A-Za-z_]\w*\s*:|$)/,
    );
    if (rel) {
      tokens.push(rel[1].trim());
      rest = rest.slice(rel[0].length);
      continue;
    }

    const applyWithBindings = rest.match(
      /^([A-Za-z_]\w*\s*:\s*\S+\s*\{[^}]*\})(?=\s+[A-Za-z_]\w*\s*<--trace--|\s+[A-Za-z_]\w*\s*:|$)/,
    );
    if (applyWithBindings) {
      tokens.push(applyWithBindings[1].trim());
      rest = rest.slice(applyWithBindings[0].length);
      continue;
    }

    const applySimple = rest.match(
      /^([A-Za-z_]\w*\s*:\s*\S+)(?=\s+[A-Za-z_]\w*\s*<--trace--|\s+[A-Za-z_]\w*\s*:|$)/,
    );
    if (applySimple) {
      tokens.push(applySimple[1].trim());
      rest = rest.slice(applySimple[0].length);
      continue;
    }

    break;
  }

  return tokens;
}

/**
 * Parse precondition/postcondition text into a graph structure for visualization.
 * Uses same symbology as rules: pre = match-like nodes, post = apply-like nodes,
 * plus relation edges (inside pre/post) and trace edges (pre -> post).
 * Returns:
 * {
 *   preNodes: [...],
 *   postNodes: [...],
 *   preRelations: [{ sourceVar, targetVar, assocName, relationVar }],
 *   postRelations: [{ sourceVar, targetVar, assocName, relationVar }],
 *   traceEdges: [{ sourceVar, targetVar }]
 * }
 */
export function parsePropertyToGraph(precondition, postcondition) {
  const preNodes = [];
  const postNodes = [];
  const preRelations = [];
  const postRelations = [];
  const traceEdges = [];
  let preId = 0;
  let postId = 0;

  const preLines = tokenizePrecondition(precondition);
  for (const line of preLines) {
    if (/^\w+\s*<--trace--\s*\w+/.test(line)) continue;
    const rel = parseRelationDeclaration(line);
    if (rel) {
      preRelations.push(rel);
      continue;
    }
    const parsed = parseMatchElementLabel(line);
    if (parsed) {
      preId += 1;
      preNodes.push({
        id: `pre_${preId}`,
        label: line,
        varName: parsed.varName,
        className: parsed.className,
        matchType: parsed.matchType,
        whereClause: parsed.whereClause ?? null,
      });
    }
  }

  const postLines = tokenizePostcondition(postcondition);
  for (const line of postLines) {
    // Match "postVar <--trace-- preVar" (apply element traced from match element); allow trailing whitespace/comments
    const traceMatch = line.match(/^\s*(\w+)\s*<--trace--\s*(\w+)\s*(?:\/\/.*)?$/);
    if (traceMatch) {
      traceEdges.push({ sourceVar: traceMatch[2], targetVar: traceMatch[1] });
      continue;
    }
    // Fallback: line contains <--trace-- anywhere (e.g. extra spaces or inline)
    if (line.includes("<--trace--")) {
      const inlineMatch = line.match(/(\w+)\s*<--trace--\s*(\w+)/);
      if (inlineMatch) {
        traceEdges.push({ sourceVar: inlineMatch[2], targetVar: inlineMatch[1] });
        continue;
      }
    }
    const rel = parseRelationDeclaration(line);
    if (rel) {
      postRelations.push(rel);
      continue;
    }
    const parsed = parseApplyElementLabel(line);
    if (parsed) {
      postId += 1;
      postNodes.push({
        id: `post_${postId}`,
        label: line,
        varName: parsed.varName,
        className: parsed.className,
        attributeBindings: parsed.attributeBindings ?? [],
      });
    }
  }

  return { preNodes, postNodes, preRelations, postRelations, traceEdges };
}
