from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable

from .concrete_model import ConcreteModel, TraceLink
from .expr_runtime import RuntimeExprEvaluator
from .model import (
    ApplyElement,
    ApplyLink,
    CompositeProperty,
    ElementId,
    MatchElement,
    MatchLink,
    Metamodel,
    Property,
    Transformation,
)
from .properties import evaluate_composite_formula
from .runtime_engine import _build_expr_env, _is_instance_of


@dataclass(frozen=True)
class ConcretePropertyResult:
    property_id: str
    property_name: str
    status: str  # "holds" | "violated" | "precondition_never_matched" | "unexpectedly_holds"
    checked_pre_matches: int
    violating_pre_match: dict[str, str] | None = None
    message: str | None = None  # Human-readable explanation


def _candidate_ids(mm: Metamodel, model: ConcreteModel, class_name: str) -> list[str]:
    out: list[str] = []
    for node_id, node in model.nodes.items():
        if _is_instance_of(mm, node.class_name, class_name):
            out.append(node_id)
    out.sort()
    return out


def _links_hold(
    model: ConcreteModel,
    links: tuple[MatchLink | ApplyLink, ...],
    binding: dict[ElementId, str],
) -> bool:
    for link in links:
        src = binding.get(link.source)
        tgt = binding.get(link.target)
        if src is None or tgt is None:
            return False
        if isinstance(link, MatchLink) and link.kind.name == "INDIRECT":
            raise NotImplementedError(
                f"Indirect property links are not supported by the concrete property checker: {link.name}"
            )
        if not model.has_edge(str(link.assoc_type), src, tgt):
            return False
    return True


def _find_bindings(
    mm: Metamodel,
    model: ConcreteModel,
    elements: tuple[MatchElement | ApplyElement, ...],
    links: tuple[MatchLink | ApplyLink, ...],
    constraint_expr,
) -> list[dict[ElementId, str]]:
    per_element_candidates: list[list[str]] = []
    ids = [e.id for e in elements]
    for e in elements:
        per_element_candidates.append(_candidate_ids(mm, model, str(e.class_type)))
    if any(len(cands) == 0 for cands in per_element_candidates):
        return []

    out: list[dict[ElementId, str]] = []
    for combo in product(*per_element_candidates):
        if len(set(combo)) != len(combo):
            continue
        binding = {elem_id: node_id for elem_id, node_id in zip(ids, combo)}
        if not _links_hold(model, links, binding):
            continue

        names = {e.id: e.name for e in elements}
        env = _build_expr_env(mm, model, binding, names)
        evaluator = RuntimeExprEvaluator(env=env)

        # Per-element where clauses (only present on MatchElement).
        keep = True
        for e in elements:
            where_clause = getattr(e, "where_clause", None)
            if where_clause is not None and not bool(evaluator.eval(where_clause)):
                keep = False
                break
        if not keep:
            continue

        if constraint_expr is not None and not bool(evaluator.eval(constraint_expr)):
            continue
        out.append(binding)
    return out


def _is_expected_violated(prop: Property) -> bool:
    """True if this property is expected to be violated (e.g. ShouldFail diagnostic)."""
    return "ShouldFail" in prop.name


def check_property_concrete(
    transformation: Transformation,
    source_model: ConcreteModel,
    target_model: ConcreteModel,
    traces: Iterable[TraceLink],
    prop: Property,
) -> ConcretePropertyResult:
    pre = prop.precondition
    if pre is None:
        pre_bindings = [dict()]
    else:
        pre_bindings = _find_bindings(
            transformation.source_metamodel,
            source_model,
            pre.elements,
            pre.links,
            pre.constraint,
        )

    if len(pre_bindings) == 0:
        return ConcretePropertyResult(
            property_id=prop.id,
            property_name=prop.name,
            status="precondition_never_matched",
            checked_pre_matches=0,
            message="precondition pattern never found in input model",
        )

    trace_pairs = {(t.source_id, t.target_id) for t in traces}
    post = prop.postcondition
    post_bindings = _find_bindings(
        transformation.target_metamodel,
        target_model,
        post.elements,
        post.links,
        post.constraint,
    )

    expected_violated = _is_expected_violated(prop)

    for pre_binding in pre_bindings:
        witnessed = False
        for post_binding in post_bindings:
            ok = True
            for post_elem, pre_elem in post.trace_links:
                src_id = pre_binding.get(pre_elem)
                tgt_id = post_binding.get(post_elem)
                if src_id is None or tgt_id is None or (src_id, tgt_id) not in trace_pairs:
                    ok = False
                    break
            if ok:
                witnessed = True
                break

        if expected_violated:
            # Post must NEVER be found. If witnessed → transformation bug.
            if witnessed:
                rendered = {str(k): v for k, v in pre_binding.items()}
                return ConcretePropertyResult(
                    property_id=prop.id,
                    property_name=prop.name,
                    status="unexpectedly_holds",
                    checked_pre_matches=len(pre_bindings),
                    violating_pre_match=rendered,
                    message="expected violated but postcondition matched; transformation may have produced incorrect output",
                )
        else:
            # Normal property: post must be found for every pre-match.
            if not witnessed:
                rendered = {str(k): v for k, v in pre_binding.items()}
                return ConcretePropertyResult(
                    property_id=prop.id,
                    property_name=prop.name,
                    status="violated",
                    checked_pre_matches=len(pre_bindings),
                    violating_pre_match=rendered,
                )

    return ConcretePropertyResult(
        property_id=prop.id,
        property_name=prop.name,
        status="violated" if expected_violated else "holds",
        checked_pre_matches=len(pre_bindings),
    )


def check_properties_concrete(
    transformation: Transformation,
    source_model: ConcreteModel,
    target_model: ConcreteModel,
    traces: Iterable[TraceLink],
    properties: tuple[Property | CompositeProperty, ...],
) -> list[ConcretePropertyResult]:
    atomic_results: dict[str, bool] = {}
    out: list[ConcretePropertyResult] = []

    for p in properties:
        if isinstance(p, Property):
            res = check_property_concrete(transformation, source_model, target_model, traces, p)
            out.append(res)
            # For composite formula: "holds" (normal) or "violated" (ShouldFail) = positive outcome
            atomic_results[p.id] = (
                res.status == "holds"
                or (res.status == "violated" and _is_expected_violated(p))
            )

    for p in properties:
        if isinstance(p, CompositeProperty):
            holds = evaluate_composite_formula(p.formula, atomic_results)
            out.append(
                ConcretePropertyResult(
                    property_id=p.id,
                    property_name=p.name,
                    status="holds" if holds else "violated",
                    checked_pre_matches=0,
                )
            )

    return out
