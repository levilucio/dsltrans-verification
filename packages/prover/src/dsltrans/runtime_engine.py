from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Optional

from .concrete_model import ConcreteModel
from .expr_runtime import RuntimeExprEvaluator
from .model import ElementId, MatchElement, MatchType, Metamodel, Rule, Transformation


@dataclass(frozen=True)
class ExecutionStats:
    layer_iterations: dict[str, int]
    applied_matches_per_rule: dict[str, int]
    created_nodes: int
    created_edges: int
    created_traces: int


def _is_instance_of(mm: Metamodel, actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    current = mm.class_by_name.get(actual)
    while current is not None and current.parent is not None:
        parent = mm.class_by_id.get(current.parent)
        if parent is None:
            break
        if parent.name == expected:
            return True
        current = parent
    return False


def _build_expr_env(
    mm: Metamodel, model: ConcreteModel, binding: dict[ElementId, str], var_names: dict[ElementId, str]
) -> dict[str, object]:
    env: dict[str, object] = {}
    for elem_id, node_id in binding.items():
        var_name = var_names[elem_id]
        env[var_name] = node_id
        node = model.nodes[node_id]
        cls = mm.class_by_name.get(node.class_name)
        if cls is None:
            continue
        # Include inherited attributes through effective hierarchy.
        seen: set[str] = set()
        current = cls
        while current is not None:
            for attr in current.attributes:
                if attr.name in seen:
                    continue
                seen.add(attr.name)
                env[f"{var_name}.{attr.name}"] = node.attrs.get(attr.name)
            if current.parent is None:
                break
            current = mm.class_by_id.get(current.parent)
    return env


def _link_exists(model: ConcreteModel, assoc_name: str, src_id: str, tgt_id: str) -> bool:
    return model.has_edge(assoc_name, src_id, tgt_id)


def _candidate_ids(mm: Metamodel, model: ConcreteModel, me: MatchElement) -> list[str]:
    candidates: list[str] = []
    expected_name = str(me.class_type)
    for node_id, node in model.nodes.items():
        if _is_instance_of(mm, node.class_name, expected_name):
            candidates.append(node_id)
    candidates.sort()
    return candidates


def _validate_match_links(
    rule: Rule, model: ConcreteModel, binding: dict[ElementId, str]
) -> bool:
    for ml in rule.match_links:
        src = binding.get(ml.source)
        tgt = binding.get(ml.target)
        if src is None or tgt is None:
            return False
        if ml.kind.name == "INDIRECT":
            raise NotImplementedError(
                f"Indirect match links are not supported by the runtime engine: {ml.name}"
            )
        if not _link_exists(model, str(ml.assoc_type), src, tgt):
            return False
    return True


def _where_and_guard_hold(
    trans: Transformation,
    rule: Rule,
    src_model: ConcreteModel,
    binding: dict[ElementId, str],
) -> bool:
    names = {me.id: me.name for me in rule.match_elements}
    env = _build_expr_env(trans.source_metamodel, src_model, binding, names)
    evaluator = RuntimeExprEvaluator(env=env)
    for me in rule.match_elements:
        if me.where_clause is None:
            continue
        if not bool(evaluator.eval(me.where_clause)):
            return False
    if rule.guard is not None and not bool(evaluator.eval(rule.guard)):
        return False
    return True


def _find_rule_matches(
    trans: Transformation,
    src_model: ConcreteModel,
    rule: Rule,
) -> list[dict[ElementId, str]]:
    per_element_candidates: list[list[str]] = []
    for me in rule.match_elements:
        cands = _candidate_ids(trans.source_metamodel, src_model, me)
        if me.match_type == MatchType.EXISTS:
            cands = cands[:1]
        per_element_candidates.append(cands)
    if any(len(cands) == 0 for cands in per_element_candidates):
        return []

    matches: list[dict[ElementId, str]] = []
    ids = [me.id for me in rule.match_elements]
    for combo in product(*per_element_candidates):
        # Enforce injective match for distinct match variables.
        if len(set(combo)) != len(combo):
            continue
        binding = {elem_id: node_id for elem_id, node_id in zip(ids, combo)}
        if not _validate_match_links(rule, src_model, binding):
            continue
        if not _where_and_guard_hold(trans, rule, src_model, binding):
            continue
        matches.append(binding)
    return matches


def _evaluate_apply_bindings(
    rule: Rule,
    evaluator: RuntimeExprEvaluator,
) -> dict[ElementId, dict[str, object]]:
    out: dict[ElementId, dict[str, object]] = {}
    for ae in rule.apply_elements:
        attrs: dict[str, object] = {}
        for bind in ae.attribute_bindings:
            attrs[bind.target.attribute] = evaluator.eval(bind.value)
        out[ae.id] = attrs
    return out


def _attrs_compatible(existing_attrs: dict[str, object], expected_attrs: dict[str, object]) -> bool:
    # For backward-linked reuse, enforce consistency with already materialized
    # output values. Missing attributes can still be initialized by this rule.
    for attr_name, expected in expected_attrs.items():
        if attr_name in existing_attrs and existing_attrs[attr_name] != expected:
            return False
    return True


def _compute_apply_mapping(
    rule: Rule,
    src_binding: dict[ElementId, str],
    tgt_model: ConcreteModel,
    created_key_to_node: dict[tuple[str, str, tuple[str, ...]], str],
    apply_attr_values: dict[ElementId, dict[str, object]],
    backward_model: Optional[ConcreteModel] = None,
) -> Optional[dict[ElementId, str]]:
    # Resolve backward links from backward_model (e.g. layer-start snapshot) so same-layer outputs are not visible.
    resolve_from = backward_model if backward_model is not None else tgt_model
    apply_map: dict[ElementId, str] = {}
    ordered_match_ids = tuple(src_binding[e.id] for e in rule.match_elements)
    bl_by_apply: dict[ElementId, list[ElementId]] = {}
    for bl in rule.backward_links:
        bl_by_apply.setdefault(bl.apply_element, []).append(bl.match_element)

    for ae in rule.apply_elements:
        if ae.id in bl_by_apply:
            key = (rule.name, str(ae.id), ordered_match_ids)
            existing = created_key_to_node.get(key)
            if existing is not None:
                expected_attrs = apply_attr_values.get(ae.id, {})
                if existing in tgt_model.nodes and _attrs_compatible(tgt_model.nodes[existing].attrs, expected_attrs):
                    apply_map[ae.id] = existing
                    continue
                return None

            candidate_sets: list[set[str]] = []
            has_empty_candidate_set = False
            for me_id in bl_by_apply[ae.id]:
                src_node_id = src_binding[me_id]
                candidates = resolve_from.get_traced_targets(src_node_id, target_class=str(ae.class_type))
                if not candidates:
                    has_empty_candidate_set = True
                    break
                candidate_sets.append(set(candidates))
            if not has_empty_candidate_set and candidate_sets:
                reused_ids = set.intersection(*candidate_sets)
                expected_attrs = apply_attr_values.get(ae.id, {})
                compatible = [
                    nid for nid in sorted(reused_ids)
                    if _attrs_compatible(tgt_model.nodes[nid].attrs, expected_attrs)
                ]
                if reused_ids:
                    if len(compatible) == 1:
                        apply_map[ae.id] = compatible[0]
                        continue
                    return None
            # Backward links require an existing traced target; do not create.
            return None

        key = (rule.name, str(ae.id), ordered_match_ids)
        existing = created_key_to_node.get(key)
        if existing is not None:
            apply_map[ae.id] = existing
            continue
        new_id = tgt_model.generate_node_id(f"{rule.name}_{ae.name}")
        tgt_model.ensure_node(new_id, str(ae.class_type))
        created_key_to_node[key] = new_id
        apply_map[ae.id] = new_id

    return apply_map


def _apply_rule_match(
    trans: Transformation,
    rule: Rule,
    src_model: ConcreteModel,
    tgt_model: ConcreteModel,
    src_binding: dict[ElementId, str],
    created_key_to_node: dict[tuple[str, str, tuple[str, ...]], str],
    backward_model: Optional[ConcreteModel] = None,
) -> tuple[bool, int, int, int]:
    changed = False
    node_created = 0
    edge_created = 0
    trace_created = 0

    existing_nodes = set(tgt_model.nodes.keys())

    match_var_names = {me.id: me.name for me in rule.match_elements}
    env = _build_expr_env(trans.source_metamodel, src_model, src_binding, match_var_names)
    evaluator = RuntimeExprEvaluator(env=env)
    apply_attr_values = _evaluate_apply_bindings(rule, evaluator)
    apply_map = _compute_apply_mapping(
        rule,
        src_binding,
        tgt_model,
        created_key_to_node,
        apply_attr_values,
        backward_model=backward_model,
    )
    if apply_map is None:
        return False, 0, 0, 0

    for node_id in tgt_model.nodes.keys():
        if node_id not in existing_nodes:
            node_created += 1
            changed = True

    backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
    created_apply_node_ids = {
        apply_map[ae.id] for ae in rule.apply_elements if apply_map[ae.id] not in existing_nodes
    }

    for ae in rule.apply_elements:
        tgt_node_id = apply_map[ae.id]
        expected_attrs = apply_attr_values.get(ae.id, {})
        for attr_name, value in expected_attrs.items():
            current = tgt_model.nodes[tgt_node_id].attrs.get(attr_name)
            if ae.id in backward_apply_ids and current is not None and current != value:
                return False, 0, 0, 0
            if tgt_model.set_attr(tgt_node_id, attr_name, value):
                changed = True

    for al in rule.apply_links:
        src_id = apply_map[al.source]
        tgt_id = apply_map[al.target]
        if tgt_model.add_edge(str(al.assoc_type), src_id, tgt_id):
            changed = True
            edge_created += 1

    # Implicit trace semantics for created outputs:
    # every matched source element traces to every newly created apply element.
    for me in rule.match_elements:
        src_id = src_binding[me.id]
        for tgt_id in sorted(created_apply_node_ids):
            if tgt_model.add_trace(src_id, tgt_id):
                changed = True
                trace_created += 1

    return changed, node_created, edge_created, trace_created


def execute_transformation(
    transformation: Transformation,
    source_model: ConcreteModel,
    max_layer_iterations: int = 200,
) -> tuple[ConcreteModel, ExecutionStats]:
    """
    Execute DSLTrans transformation on a concrete source model.

    Semantics used:
      - Layer execution at fixpoint (user-requested).
      - Backward links resolve only from the target graph at layer start (Lucio2014-style
        “glue”): each layer sees the complete output of the previous layer; rules in the
        same layer do not see each other’s apply elements or traces until the next layer.
      - All matches are applied; duplicate prevention by construction for created elements/links.
      - Backward links bind to unique, existing traced target elements (from layer snapshot).
      - Backward links do not create traces.
      - New apply elements receive implicit cartesian traces from matched inputs.
    """
    target = ConcreteModel()
    created_key_to_node: dict[tuple[str, str, tuple[str, ...]], str] = {}
    applied_per_rule: dict[str, int] = {}
    layer_iterations: dict[str, int] = {}
    total_nodes = 0
    total_edges = 0
    total_traces = 0

    for layer in transformation.layers:
        # Backward links resolve only from target state at layer start (Lucio2014-style “glue” semantics).
        layer_snapshot = target.snapshot()
        changed = True
        iterations = 0
        while changed:
            iterations += 1
            if iterations > max_layer_iterations:
                raise RuntimeError(
                    f"Layer {layer.name} exceeded max iterations ({max_layer_iterations}); "
                    "possible non-converging rule set under current runtime semantics."
                )
            changed = False
            for rule in layer.rules:
                matches = _find_rule_matches(transformation, source_model, rule)
                if not matches:
                    continue
                for m in matches:
                    did_change, created_nodes, created_edges, created_traces = _apply_rule_match(
                        transformation, rule, source_model, target, m, created_key_to_node,
                        backward_model=layer_snapshot,
                    )
                    if did_change:
                        changed = True
                    total_nodes += created_nodes
                    total_edges += created_edges
                    total_traces += created_traces
                    if did_change:
                        applied_per_rule[rule.name] = applied_per_rule.get(rule.name, 0) + 1
        layer_iterations[layer.name] = iterations

    return target, ExecutionStats(
        layer_iterations=layer_iterations,
        applied_matches_per_rule=applied_per_rule,
        created_nodes=total_nodes,
        created_edges=total_edges,
        created_traces=total_traces,
    )
