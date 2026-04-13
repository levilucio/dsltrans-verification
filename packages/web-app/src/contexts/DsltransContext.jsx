import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { createEdge, createNode, moveNode, NODE_KINDS } from "@/utils/dsltransModel";
import { ruleBasedLayout } from "@/features/layout/ruleLayout";
import {
  buildLayoutIndex,
  buildMatchLine,
  buildApplyLine,
  parseDsltransToGraph,
  serializeDsltrans,
} from "@/utils/dsltransSerializer";

const DsltransContext = createContext(null);
const SPEC_STORAGE_KEY = "dsltrans-studio-spec";

function buildDefaultState() {
  const layerId = uuidv4();
  const rule = createNode(NODE_KINDS.RULE, "Rule1", 80, 60, { layerId });
  const doc = {
    layers: [{ id: layerId, name: "Layer1", index: 0 }],
    nodes: [
      rule,
      createNode(NODE_KINDS.MATCH, "src : Class", 0, 0, { parentRuleId: rule.id, layerId }),
      createNode(NODE_KINDS.APPLY, "tgt : Table", 0, 0, { parentRuleId: rule.id, layerId }),
    ],
    edges: [],
  };
  const laidOut = { ...doc, nodes: ruleBasedLayout(doc.layers, doc.nodes) };
  return {
    ...laidOut,
    specText: serializeDsltrans(laidOut),
    _layoutIndex: buildLayoutIndex(laidOut),
    documentMode: "fragment",
    modeLocked: true,
    fragmentStatus: null,
  };
}

function initialState() {
  const fallback = buildDefaultState();
  if (typeof window === "undefined") return fallback;
  const stored = window.localStorage.getItem(SPEC_STORAGE_KEY);
  if (!stored) return fallback;
  try {
    const graph = parseDsltransToGraph(stored, fallback);
    const laidOut = {
      ...graph,
      nodes: ruleBasedLayout(graph.layers, graph.nodes),
    };
    return {
      ...laidOut,
      specText: stored,
      _layoutIndex: buildLayoutIndex(laidOut),
      documentMode: laidOut.documentMode ?? "fragment",
      modeLocked: true,
      fragmentStatus: laidOut.fragmentStatus ?? null,
    };
  } catch {
    return fallback;
  }
}

export function DsltransProvider({ children }) {
  const [history, setHistory] = useState([initialState()]);
  const [pointer, setPointer] = useState(0);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [snapToGridEnabled, setSnapToGridEnabled] = useState(true);
  const [pendingEdgeSourceId, setPendingEdgeSourceId] = useState(null);
  const [transformationSourceMetamodel, setTransformationSourceMetamodel] = useState(null);
  const [transformationTargetMetamodel, setTransformationTargetMetamodel] = useState(null);
  const [transformationSourceMetamodelDetail, setTransformationSourceMetamodelDetail] = useState(null);
  const [transformationTargetMetamodelDetail, setTransformationTargetMetamodelDetail] = useState(null);
  const state = history[pointer];

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(SPEC_STORAGE_KEY, state.specText ?? "");
  }, [state.specText]);

  const setTransformationMetamodels = useCallback((sourceName, targetName, sourceDetail = null, targetDetail = null) => {
    setTransformationSourceMetamodel(sourceName ?? null);
    setTransformationTargetMetamodel(targetName ?? null);
    setTransformationSourceMetamodelDetail(sourceDetail ?? null);
    setTransformationTargetMetamodelDetail(targetDetail ?? null);
  }, []);

  const commit = useCallback(
    (nextState, options = {}) => {
      const text = options.specText ?? serializeDsltrans(nextState);
      const mergedState = {
        ...nextState,
        specText: text,
        _layoutIndex: buildLayoutIndex(nextState),
        documentMode: nextState.documentMode ?? state.documentMode,
        modeLocked: nextState.modeLocked ?? state.modeLocked,
        fragmentStatus: nextState.fragmentStatus !== undefined ? nextState.fragmentStatus : state.fragmentStatus,
      };
      const nextHistory = history.slice(0, pointer + 1);
      nextHistory.push(mergedState);
      setHistory(nextHistory);
      setPointer(nextHistory.length - 1);
    },
    [history, pointer, state.documentMode, state.modeLocked, state.fragmentStatus],
  );

  const updateDocumentModeLocked = useCallback((mode, status) => {
    setHistory((prev) => {
      const idx = prev.length - 1;
      const current = prev[idx];
      return [...prev.slice(0, idx), { ...current, documentMode: mode, modeLocked: true, fragmentStatus: status }];
    });
  }, []);

  const newFragmentDocument = useCallback(() => {
    setHistory([initialState()]);
    setPointer(0);
    setTransformationSourceMetamodel(null);
    setTransformationTargetMetamodel(null);
    setTransformationSourceMetamodelDetail(null);
    setTransformationTargetMetamodelDetail(null);
  }, []);

  const newNonFragmentDocument = useCallback(() => {
    const next = { ...initialState(), documentMode: "non-fragment", modeLocked: true, fragmentStatus: { loadable: false, violations: ["Non-fragment document; verification/cutoff may not apply."] } };
    setHistory([next]);
    setPointer(0);
    setTransformationSourceMetamodel(null);
    setTransformationTargetMetamodel(null);
    setTransformationSourceMetamodelDetail(null);
    setTransformationTargetMetamodelDetail(null);
  }, []);

  const setSpecTextAndSync = useCallback(
    (text) => {
      const graph = parseDsltransToGraph(text, state);
      const laidOut = {
        ...graph,
        nodes: ruleBasedLayout(graph.layers, graph.nodes),
      };
      commit(laidOut, { specText: text });
    },
    [commit, state],
  );

  const addLayer = useCallback(() => {
    const id = uuidv4();
    commit({
      ...state,
      layers: [...state.layers, { id, name: `Layer${state.layers.length + 1}`, index: state.layers.length }],
    });
  }, [commit, state]);

  const addRule = useCallback(
    (layerId) => {
      const nextState = { ...state, nodes: [...state.nodes] };
      const layerIndex = state.layers.find((l) => l.id === layerId)?.index || 0;
      const ruleCount = state.nodes.filter((n) => n.layerId === layerId && n.kind === NODE_KINDS.RULE).length;
      const x = 80 + layerIndex * 400 + (ruleCount % 3) * 280;
      const y = 60 + Math.floor(ruleCount / 3) * 200;
      const rule = createNode(NODE_KINDS.RULE, `Rule${state.nodes.filter((n) => n.kind === NODE_KINDS.RULE).length + 1}`, x, y, {
        layerId,
      });
      nextState.nodes.push(rule);
      commit({ ...nextState, nodes: ruleBasedLayout(nextState.layers, nextState.nodes) });
    },
    [commit, state],
  );

  const addRuleElement = useCallback(
    (ruleId, kind) => {
      const rule = state.nodes.find((n) => n.id === ruleId);
      if (!rule) return;
      const sameKindCount = state.nodes.filter((n) => n.parentRuleId === ruleId && n.kind === kind).length;
      const label = kind === NODE_KINDS.MATCH ? `m${sameKindCount + 1} : Type` : `a${sameKindCount + 1} : Type`;
      const node = createNode(kind, label, 0, 0, { parentRuleId: ruleId, layerId: rule.layerId });
      const nextState = { ...state, nodes: [...state.nodes, node] };
      commit({ ...nextState, nodes: ruleBasedLayout(nextState.layers, nextState.nodes) });
    },
    [commit, state],
  );

  const moveCanvasNode = useCallback(
    (nodeId, x, y) => {
      commit({
        ...state,
        nodes: state.nodes.map((n) => (n.id === nodeId ? moveNode(n, x, y, snapToGridEnabled) : n)),
      });
    },
    [commit, snapToGridEnabled, state],
  );

  const startEdgeCreation = useCallback((nodeId) => setPendingEdgeSourceId(nodeId), []);

  const completeEdgeCreation = useCallback(
    (targetId, edgeType = "direct", label = "") => {
      if (!pendingEdgeSourceId || pendingEdgeSourceId === targetId) return;
      const edge = createEdge(pendingEdgeSourceId, targetId, edgeType, label);
      commit({ ...state, edges: [...state.edges, edge] });
      setPendingEdgeSourceId(null);
    },
    [commit, pendingEdgeSourceId, state],
  );

  const deleteSelected = useCallback(() => {
    if (!selectedNodeId) return;
    const nodeIdsToDelete = new Set([selectedNodeId]);
    state.nodes.forEach((n) => {
      if (n.parentRuleId === selectedNodeId) nodeIdsToDelete.add(n.id);
    });
    const nextState = {
      ...state,
      nodes: state.nodes.filter((n) => !nodeIdsToDelete.has(n.id)),
      edges: state.edges.filter((e) => !nodeIdsToDelete.has(e.sourceId) && !nodeIdsToDelete.has(e.targetId)),
    };
    commit({ ...nextState, nodes: ruleBasedLayout(nextState.layers, nextState.nodes) });
    setSelectedNodeId(null);
  }, [commit, selectedNodeId, state]);

  const updateNodeLabel = useCallback(
    (nodeId, label) => {
      commit({ ...state, nodes: state.nodes.map((n) => (n.id === nodeId ? { ...n, label } : n)) });
    },
    [commit, state],
  );

  const updateElementNode = useCallback(
    (nodeId, updates) => {
      const nextNodes = state.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const merged = { ...n, ...updates };
        const label =
          n.kind === NODE_KINDS.MATCH ? buildMatchLine(merged) : buildApplyLine(merged);
        return { ...merged, label };
      });
      commit({ ...state, nodes: ruleBasedLayout(state.layers, nextNodes) });
    },
    [commit, state],
  );

  const autoLayout = useCallback(() => {
    commit({ ...state, nodes: ruleBasedLayout(state.layers, state.nodes) });
  }, [commit, state]);

  const undo = useCallback(() => {
    setPointer((value) => Math.max(0, value - 1));
  }, []);

  const redo = useCallback(() => {
    setPointer((value) => Math.min(history.length - 1, value + 1));
  }, [history.length]);

  const value = useMemo(
    () => ({
      ...state,
      documentMode: state.documentMode ?? "fragment",
      modeLocked: state.modeLocked ?? true,
      fragmentStatus: state.fragmentStatus ?? null,
      selectedNodeId,
      setSelectedNodeId,
      snapToGridEnabled,
      setSnapToGridEnabled,
      pendingEdgeSourceId,
      specText: state.specText,
      transformationSourceMetamodel,
      transformationTargetMetamodel,
      transformationSourceMetamodelDetail,
      transformationTargetMetamodelDetail,
      setTransformationMetamodels,
      updateDocumentModeLocked,
      newFragmentDocument,
      newNonFragmentDocument,
      addLayer,
      addRule,
      addRuleElement,
      moveCanvasNode,
      startEdgeCreation,
      completeEdgeCreation,
      deleteSelected,
      updateNodeLabel,
      updateElementNode,
      autoLayout,
      setSpecTextAndSync,
      undo,
      redo,
      canUndo: pointer > 0,
      canRedo: pointer < history.length - 1,
    }),
    [
      state,
      selectedNodeId,
      snapToGridEnabled,
      pendingEdgeSourceId,
      state.specText,
      state.documentMode,
      state.modeLocked,
      state.fragmentStatus,
      transformationSourceMetamodel,
      transformationTargetMetamodel,
      transformationSourceMetamodelDetail,
      transformationTargetMetamodelDetail,
      setTransformationMetamodels,
      updateDocumentModeLocked,
      newFragmentDocument,
      newNonFragmentDocument,
      addLayer,
      addRule,
      addRuleElement,
      moveCanvasNode,
      startEdgeCreation,
      completeEdgeCreation,
      deleteSelected,
      updateNodeLabel,
      updateElementNode,
      autoLayout,
      setSpecTextAndSync,
      undo,
      redo,
      pointer,
      history.length,
    ],
  );

  return <DsltransContext.Provider value={value}>{children}</DsltransContext.Provider>;
}

export function useDsltrans() {
  const context = useContext(DsltransContext);
  if (!context) throw new Error("useDsltrans must be used inside DsltransProvider");
  return context;
}
