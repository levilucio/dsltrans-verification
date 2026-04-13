#!/usr/bin/env python3
"""
Unified property-proof runner with CEGAR refinement.

Runs property verification for any DSLTrans transformation spec from
`examples/` and writes a markdown report under `docs/`.

Core flow:
- minimal satisfying fragment + cutoff K
- optional strategy selection (strict/path-depth/relaxed)
- CEGAR-style refinement for VIOLATED on minimal fragment
- optional baseline fallback when needed
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dsltrans.abstraction import (
    AbstractionPolicy,
    make_default_abstraction_policy,
    synthesize_abstract_spec_for_property,
)
from dsltrans.parser import parse_dsltrans_file
from dsltrans.cutoff import (
    check_fragment,
    build_fragment,
    get_relevant_rules,
    layer_indices_for_rules,
    minimal_satisfying_layer_indices,
    compute_cutoff_bound,
    compute_cutoff_bound_detailed,
)
from dsltrans.smt_direct import SMTDirectConfig, SMTDirectVerifier

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
DOCS_DIR = Path(__file__).resolve().parent / "docs" / "05_evaluation_and_results" / "case_studies"
DEFAULT_SPEC = "class2relational_concrete.dslt"


def _default_report_path(spec_name: str) -> Path:
    stem = Path(spec_name).stem
    return DOCS_DIR / f"{stem}_proof_results.md"


def _materialize_property_spec(
    base_spec,
    prop,
    abstraction_policy: AbstractionPolicy | None,
):
    if abstraction_policy is None:
        return base_spec, prop
    abstract_result = synthesize_abstract_spec_for_property(base_spec, abstraction_policy, prop.name)
    abstract_spec = abstract_result.abstract_spec
    return abstract_spec, abstract_spec.properties[0]


def _print_counterexample(ce: dict) -> None:
    """Print a counterexample dict from the verifier in a readable form."""
    if not ce:
        return
    print("    Counterexample:", flush=True)
    for k, v in ce.get("source_elements", {}).items():
        if v:
            print(f"      source {k}: indices {v}", flush=True)
    for k, v in ce.get("target_elements", {}).items():
        if v:
            print(f"      target {k}: indices {v}", flush=True)
    for k, v in ce.get("source_links", {}).items():
        if v:
            print(f"      source link {k}: {v}", flush=True)
    for k, v in ce.get("target_links", {}).items():
        if v:
            print(f"      target link {k}: {v}", flush=True)
    firings = ce.get("rule_firings", [])
    if firings:
        print(f"      rule_firings: {len(firings)}", flush=True)
        for f in firings[:20]:
            print(f"        {f}", flush=True)
        if len(firings) > 20:
            print(f"        ... and {len(firings) - 20} more", flush=True)


def _verify_with_fragment(
    spec,
    prop,
    fragment_trans,
    K,
    timeout_ms,
    relax_containment: bool = False,
    per_class_heuristic_confirm: bool = False,
    strict_per_class_bounds: bool = False,
):
    frag_spec = type(spec)(
        metamodels=spec.metamodels,
        transformations=(fragment_trans,),
        properties=(prop,),
    )

    def _run_once(use_per_class_bounds: bool):
        config = SMTDirectConfig(
            bound=K,
            use_cutoff=False,
            timeout_ms=timeout_ms if timeout_ms > 0 else None,
            use_property_slicing=True,
            use_metamodel_slicing=True,
            reduce_unused_string_domains=True,
            prune_unconsumed_trace_producers=True,
            use_per_class_type_bounds=use_per_class_bounds,
            per_class_bounds_analysis="fixed_point",
            relax_source_containment_for_proving=relax_containment,
        )
        verifier = SMTDirectVerifier(frag_spec, config)
        return verifier.verify_property(prop)

    # Two-phase profile: fast per-class pass, then confirm for HOLDS.
    if per_class_heuristic_confirm:
        fast_res = _run_once(use_per_class_bounds=True)
        if fast_res.result.name != "HOLDS":
            return fast_res, False, False
        use_per_class_in_strict = strict_per_class_bounds
        strict_res = _run_once(use_per_class_bounds=use_per_class_in_strict)
        strict_res.time_ms = float(fast_res.time_ms) + float(strict_res.time_ms)
        return strict_res, True, False

    return _run_once(use_per_class_bounds=False), False, False


import multiprocessing

def _verify_with_fragment_isolated(**kwargs):
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(1) as pool:
        return pool.apply(_verify_with_fragment, kwds=kwargs)


MAX_FALLBACK_K = 250
MAX_CEGAR_ITERS = 3


def _rule_source_match_possible(rule, ce: dict) -> bool:
    """
    Conservative (over-approximating) source-side applicability check.

    Returns True when a source binding satisfying rule match *may* exist in the
    concrete counterexample source model. Returns False only when rule matching
    is impossible from source element/link structure alone.

    Notes:
    - Uses only source element existence + direct source links.
    - Ignores guards/where clauses and backward-link trace requirements on
      purpose (over-approximation): this avoids false negatives.
    """
    if not isinstance(ce, dict):
        return True
    src_elems = ce.get("source_elements", {}) or {}
    src_links = ce.get("source_links", {}) or {}

    elem_domains: dict = {}
    for me in rule.match_elements:
        cls_name = str(me.class_type)
        domain = list(src_elems.get(cls_name, []))
        if not domain:
            return False
        elem_domains[me.id] = domain

    link_constraints: list[tuple] = []
    for ml in rule.match_links:
        # Keep only hard, direct source-link constraints.
        if str(getattr(ml, "kind", "")) != "LinkKind.DIRECT" and getattr(ml, "kind", None) is not None:
            continue
        assoc_name = str(ml.assoc_type)
        pairs = set(tuple(p) for p in (src_links.get(assoc_name, []) or []))
        if not pairs:
            return False
        link_constraints.append((ml.source, ml.target, pairs))

    ordered_vars = sorted(elem_domains.keys(), key=lambda vid: len(elem_domains[vid]))
    assigned: dict = {}

    def _consistent_so_far() -> bool:
        for src_id, tgt_id, pairs in link_constraints:
            if src_id in assigned and tgt_id in assigned:
                if (assigned[src_id], assigned[tgt_id]) not in pairs:
                    return False
        return True

    def _search(i: int) -> bool:
        if i >= len(ordered_vars):
            return True
        vid = ordered_vars[i]
        for v in elem_domains[vid]:
            assigned[vid] = v
            if _consistent_so_far() and _search(i + 1):
                return True
            assigned.pop(vid, None)
        return False

    return _search(0)


def _cegar_confirm_violated(
    *,
    spec,
    prop,
    full_trans,
    initial_res,
    initial_layers: list[int],
    initial_k: int,
    baseline_layers: list[int],
    dependency_mode: str,
    timeout_ms: int,
    relax_containment: bool,
    per_class_heuristic_confirm: bool,
    strict_per_class_bounds: bool,
):
    """
    Confirm/refine a VIOLATED result with CE-guided rule refinement.

    Starting from the current fragment, iteratively add only omitted baseline
    rules that can still match on the concrete source-side counterexample.
    """
    current_res = initial_res
    current_layers = list(initial_layers)
    current_k = int(initial_k)

    all_rules = {r.id: r for r in full_trans.all_rules}
    baseline_rule_ids = {
        r.id
        for i, layer in enumerate(full_trans.layers)
        if i in set(baseline_layers)
        for r in layer.rules
    }

    for _ in range(MAX_CEGAR_ITERS):
        if current_res.result.name != "VIOLATED":
            return current_res, current_layers, current_k, "resolved"

        ce = getattr(current_res, "counterexample", None)
        if not isinstance(ce, dict):
            return current_res, current_layers, current_k, "no_counterexample_data"

        current_rule_ids = {
            r.id
            for i, layer in enumerate(full_trans.layers)
            if i in set(current_layers)
            for r in layer.rules
        }
        omitted = sorted(rid for rid in baseline_rule_ids if rid not in current_rule_ids)
        if not omitted:
            return current_res, current_layers, current_k, "baseline_reached"

        matching_omitted = {
            rid for rid in omitted
            if _rule_source_match_possible(all_rules[rid], ce)
        }
        if not matching_omitted:
            return current_res, current_layers, current_k, "certified_no_omitted_match"

        next_rule_ids = set(current_rule_ids) | set(matching_omitted)
        next_layers = layer_indices_for_rules(full_trans, next_rule_ids)
        if next_layers == current_layers:
            return current_res, current_layers, current_k, "stuck_no_layer_growth"

        refined_frag = build_fragment(full_trans, next_layers)
        next_k = compute_cutoff_bound(
            refined_frag,
            prop,
            use_reduced_k=True,
            dependency_mode=dependency_mode,
        )
        if next_k > MAX_FALLBACK_K:
            return current_res, current_layers, current_k, "refined_k_too_large"

        print(
            f"VIOLATED; CEGAR refine K={next_k} layers {next_layers} (+{len(matching_omitted)} rules) ... ",
            end="",
            flush=True,
        )
        current_res, _, _ = _verify_with_fragment_isolated(
            spec=spec,
            prop=prop,
            fragment_trans=refined_frag,
            K=next_k,
            timeout_ms=timeout_ms,
            relax_containment=relax_containment,
            per_class_heuristic_confirm=per_class_heuristic_confirm,
            strict_per_class_bounds=strict_per_class_bounds,
        )
        current_layers = next_layers
        current_k = next_k

    return current_res, current_layers, current_k, "max_iters"


def _compute_best_strategy_for_property(full_trans, prop, dependency_mode: str, max_k: int):
    """Compute K for minimal fragment under strict, path_depth, and relaxed. Return (best_K, strategy, use_relaxed, min_frag, min_layers, baseline_frag, baseline_layers, K_baseline)."""
    min_layers = minimal_satisfying_layer_indices(full_trans, prop)
    min_frag = build_fragment(full_trans, min_layers)
    # Baseline layers from trace_attr_aware relevant rules (match K table)
    details_full = compute_cutoff_bound_detailed(
        full_trans,
        prop,
        use_reduced_k=True,
        dependency_mode=dependency_mode,
    )
    baseline_layers = layer_indices_for_rules(full_trans, set(details_full.relevant_rule_ids))
    baseline_frag = build_fragment(full_trans, baseline_layers)

    def k_min(use_path: bool, use_relaxed: bool):
        d = compute_cutoff_bound_detailed(
            min_frag,
            prop,
            use_reduced_k=True,
            dependency_mode=dependency_mode,
            use_path_aware_depth=use_path,
            ignore_containment_for_arity=use_relaxed,
        )
        return d.bound

    def k_baseline(use_path: bool, use_relaxed: bool):
        d = compute_cutoff_bound_detailed(
            baseline_frag,
            prop,
            use_reduced_k=True,
            dependency_mode=dependency_mode,
            use_path_aware_depth=use_path,
            ignore_containment_for_arity=use_relaxed,
        )
        return d.bound

    k_strict = k_min(False, False)
    k_path = k_min(True, False)
    k_relaxed = k_min(False, True)
    k_base_strict = k_baseline(False, False)
    k_base_path = k_baseline(True, False)
    k_base_relaxed = k_baseline(False, True)

    non_relaxed = [
        ("strict", False, k_strict, k_base_strict),
        ("path_depth", False, k_path, k_base_path),
    ]
    relaxed_only = [("relaxed", True, k_relaxed, k_base_relaxed)]

    # Prefer non-relaxed strategies when available under max_k.
    # Relaxed proving can reduce K but may enlarge the search space substantially.
    candidate_pool = [x for x in non_relaxed if x[2] < max_k]
    if not candidate_pool:
        candidate_pool = [x for x in relaxed_only if x[2] < max_k]

    best_k = None
    best_strategy = None
    best_relaxed = False
    best_k_baseline = None
    for (strat, relaxed, k, k_base) in candidate_pool:
        if best_k is None or k < best_k:
            best_k = k
            best_strategy = strat
            best_relaxed = relaxed
            best_k_baseline = k_base
    return (
        best_k,
        best_strategy,
        best_relaxed,
        min_frag,
        min_layers,
        baseline_frag,
        baseline_layers,
        best_k_baseline if best_k is not None else None,
    )


def run_proof(
    timeout_ms: int,
    dependency_mode: str = "trace_attr_aware",
    property_filter: list[str] | None = None,
    smoke: bool = False,
    max_k: int = 90,
    use_all_strategies: bool = False,
    confirm_shouldfail: bool = False,
    per_class_heuristic_confirm: bool = False,
    strict_per_class_bounds: bool = False,
    spec_name: str = DEFAULT_SPEC,
    per_property_concrete_spec_name: str | None = None,
    out_path: Path | None = None,
) -> list[dict]:
    source_spec_name = per_property_concrete_spec_name or spec_name
    path = EXAMPLES_DIR / source_spec_name
    if not path.exists():
        print(f"Spec not found: {path}", flush=True)
        return []
    spec = parse_dsltrans_file(path)
    if not spec.transformations or not spec.properties:
        print("No transformation or properties", flush=True)
        return []
    abstraction_policy = make_default_abstraction_policy(spec) if per_property_concrete_spec_name else None
    display_spec = Path(source_spec_name).name
    output_path = out_path or _default_report_path(display_spec)
    props_to_run = spec.properties
    if property_filter:
        names = set(property_filter)
        props_to_run = [p for p in spec.properties if p.name in names]
        if len(props_to_run) != len(names):
            missing = names - {p.name for p in props_to_run}
            print(f"Unknown property names: {missing}", flush=True)

    if use_all_strategies:
        # Build list of (prop, best_K, strategy, use_relaxed, min_frag, min_layers, baseline_frag, baseline_layers, K_baseline) for props with best K < max_k
        candidates = []
        for prop in props_to_run:
            spec_for_prop, abstract_prop = _materialize_property_spec(spec, prop, abstraction_policy)
            full_trans = spec_for_prop.transformations[0]
            in_frag, _ = check_fragment(full_trans, abstract_prop)
            if not in_frag:
                print(f"  {display_spec} / {prop.name}: not in fragment (skip)", flush=True)
                continue
            out = _compute_best_strategy_for_property(full_trans, abstract_prop, dependency_mode, max_k)
            best_k, best_strategy, best_relaxed, min_frag, min_layers, baseline_frag, baseline_layers, k_baseline = out
            if best_k is None:
                print(f"  {display_spec} / {prop.name}: min K >= {max_k} (skip)", flush=True)
                continue
            candidates.append((spec_for_prop, abstract_prop, best_k, best_strategy, best_relaxed, min_frag, min_layers, baseline_frag, baseline_layers, k_baseline))
        candidates.sort(key=lambda x: (x[2], x[1].name))
        all_rows = []
        for spec_for_prop, prop, best_k, strategy, use_relaxed, min_frag, min_layers, baseline_frag, baseline_layers, k_baseline in candidates:
            full_trans = spec_for_prop.transformations[0]
            print(f"  {display_spec} / {prop.name} (K={best_k} {strategy}) ... ", end="", flush=True)
            res, used_strict_confirm, _ = _verify_with_fragment_isolated(
                spec=spec_for_prop,
                prop=prop,
                fragment_trans=min_frag,
                K=best_k,
                timeout_ms=timeout_ms,
                relax_containment=use_relaxed,
                per_class_heuristic_confirm=per_class_heuristic_confirm,
                strict_per_class_bounds=strict_per_class_bounds,
            )
            final_k = best_k
            # Skip baseline fallback for _ShouldFail unless --confirm-shouldfail (VIOLATED is expected).
            do_fallback = (
                not smoke
                and res.result.name == "VIOLATED"
                and min_layers != baseline_layers
                and k_baseline is not None
                and k_baseline < max_k
                and k_baseline <= MAX_FALLBACK_K
            )
            if do_fallback and ("_ShouldFail" not in prop.name or confirm_shouldfail):
                # CEGAR-style confirmation first: refine only with omitted rules
                # that can still match in the concrete counterexample source model.
                res, refined_layers, refined_k, cegar_status = _cegar_confirm_violated(
                    spec=spec_for_prop,
                    prop=prop,
                    full_trans=full_trans,
                    initial_res=res,
                    initial_layers=min_layers,
                    initial_k=best_k,
                    baseline_layers=baseline_layers,
                    dependency_mode=dependency_mode,
                    timeout_ms=timeout_ms,
                    relax_containment=use_relaxed,
                    per_class_heuristic_confirm=per_class_heuristic_confirm,
                    strict_per_class_bounds=strict_per_class_bounds,
                )
                final_k = refined_k
                if cegar_status in ("baseline_reached", "refined_k_too_large") and res.result.name == "VIOLATED":
                    print(f"VIOLATED; fallback K={k_baseline} ... ", end="", flush=True)
                    res, used_strict_confirm, _ = _verify_with_fragment_isolated(
                        spec=spec_for_prop,
                        prop=prop,
                        fragment_trans=baseline_frag,
                        K=k_baseline,
                        timeout_ms=timeout_ms,
                        relax_containment=use_relaxed,
                        per_class_heuristic_confirm=per_class_heuristic_confirm,
                        strict_per_class_bounds=strict_per_class_bounds,
                    )
                    final_k = k_baseline
            # VIOLATED with a counterexample is a definitive verdict; HOLDS is complete only when strict.
            is_complete = (
                res.result.name == "VIOLATED"
                or ((not use_relaxed) and (not per_class_heuristic_confirm or used_strict_confirm))
            )
            row = {
                "spec": display_spec,
                "property": prop.name,
                "K": final_k,
                "strategy": strategy,
                "bound_used": res.bound_used,
                "result": res.result.name,
                "time_ms": round(res.time_ms, 1),
                "is_complete": is_complete,
                "experimental": False,
            }
            all_rows.append(row)
            if res.result.name == "UNKNOWN":
                print(f"{res.result.name} ({res.time_ms:.0f} ms, reason: {res.message})", flush=True)
            else:
                print(f"{res.result.name} ({res.time_ms:.0f} ms)", flush=True)
            if res.result.name == "VIOLATED" and getattr(res, "counterexample", None):
                _print_counterexample(res.counterexample)
            write_results_md(
                all_rows,
                spec_name=display_spec,
                out_path=output_path,
                dependency_mode=dependency_mode,
                smoke=smoke,
                max_k=max_k,
                use_all_strategies=use_all_strategies,
                confirm_shouldfail=confirm_shouldfail,
                per_class_heuristic_confirm=per_class_heuristic_confirm,
                strict_per_class_bounds=strict_per_class_bounds,
                per_property_concrete_spec_name=per_property_concrete_spec_name,
            )
        return all_rows

    # Original single-strategy (strict only) behaviour
    all_rows = []
    for prop in props_to_run:
        spec_for_prop, abstract_prop = _materialize_property_spec(spec, prop, abstraction_policy)
        full_trans = spec_for_prop.transformations[0]
        in_frag, _ = check_fragment(full_trans, abstract_prop)
        if not in_frag:
            print(f"  {display_spec} / {prop.name}: not in fragment (skip)", flush=True)
            continue
        min_layers = minimal_satisfying_layer_indices(full_trans, abstract_prop)
        min_frag = build_fragment(full_trans, min_layers)
        K_min = compute_cutoff_bound(min_frag, abstract_prop, use_reduced_k=True, dependency_mode=dependency_mode)
        if smoke and K_min >= max_k:
            print(f"  {display_spec} / {prop.name}: K={K_min} >= {max_k} (skip)", flush=True)
            continue
        baseline_layers = layer_indices_for_rules(full_trans, get_relevant_rules(full_trans, abstract_prop))
        print(f"  {display_spec} / {prop.name} (K={K_min} layers {min_layers}) ... ", end="", flush=True)
        res, used_strict_confirm, _ = _verify_with_fragment_isolated(
            spec=spec_for_prop,
            prop=abstract_prop,
            fragment_trans=min_frag,
            K=K_min,
            timeout_ms=timeout_ms,
            per_class_heuristic_confirm=per_class_heuristic_confirm,
            strict_per_class_bounds=strict_per_class_bounds,
        )
        if not smoke:
            # Skip baseline fallback for _ShouldFail unless --confirm-shouldfail.
            if (
                res.result.name == "VIOLATED"
                and min_layers != baseline_layers
                and ("_ShouldFail" not in prop.name or confirm_shouldfail)
            ):
                baseline_frag = build_fragment(full_trans, baseline_layers)
                K_base = compute_cutoff_bound(
                    baseline_frag,
                    abstract_prop,
                    use_reduced_k=True,
                    dependency_mode=dependency_mode,
                )
                # CEGAR-style confirmation first.
                res, _, refined_k, cegar_status = _cegar_confirm_violated(
                    spec=spec_for_prop,
                    prop=abstract_prop,
                    full_trans=full_trans,
                    initial_res=res,
                    initial_layers=min_layers,
                    initial_k=K_min,
                    baseline_layers=baseline_layers,
                    dependency_mode=dependency_mode,
                    timeout_ms=timeout_ms,
                    relax_containment=False,
                    per_class_heuristic_confirm=per_class_heuristic_confirm,
                    strict_per_class_bounds=strict_per_class_bounds,
                )
                K_min = refined_k
                if cegar_status in ("baseline_reached", "refined_k_too_large") and res.result.name == "VIOLATED":
                    if K_base <= MAX_FALLBACK_K:
                        print(f"VIOLATED; fallback K={K_base} ... ", end="", flush=True)
                        res, used_strict_confirm, _ = _verify_with_fragment_isolated(
                            spec=spec_for_prop,
                            prop=abstract_prop,
                            fragment_trans=baseline_frag,
                            K=K_base,
                            timeout_ms=timeout_ms,
                            per_class_heuristic_confirm=per_class_heuristic_confirm,
                            strict_per_class_bounds=strict_per_class_bounds,
                        )
                        K_min = K_base
                    else:
                        print(f"VIOLATED (baseline K={K_base} skipped) ", end="", flush=True)
        # VIOLATED with a counterexample is a definitive verdict; HOLDS is complete when strict confirm used or no per-class heuristic.
        is_complete = (
            res.result.name == "VIOLATED"
            or (not per_class_heuristic_confirm)
            or used_strict_confirm
        )
        row = {
            "spec": display_spec,
            "property": prop.name,
            "K": K_min,
            "bound_used": res.bound_used,
            "result": res.result.name,
            "time_ms": round(res.time_ms, 1),
            "is_complete": is_complete,
            "experimental": False,
        }
        all_rows.append(row)
        print(f"{res.result.name} ({res.time_ms:.0f} ms)", flush=True)
        if res.result.name == "VIOLATED" and getattr(res, "counterexample", None):
            _print_counterexample(res.counterexample)
        write_results_md(
            all_rows,
            spec_name=display_spec,
            out_path=output_path,
            dependency_mode=dependency_mode,
            smoke=smoke,
            max_k=max_k,
            confirm_shouldfail=confirm_shouldfail,
            per_class_heuristic_confirm=per_class_heuristic_confirm,
            strict_per_class_bounds=strict_per_class_bounds,
            per_property_concrete_spec_name=per_property_concrete_spec_name,
        )
    return all_rows


def write_results_md(
    rows: list[dict],
    spec_name: str,
    out_path: Path,
    dependency_mode: str,
    smoke: bool = False,
    max_k: int = 90,
    use_all_strategies: bool = False,
    confirm_shouldfail: bool = False,
    per_class_heuristic_confirm: bool = False,
    strict_per_class_bounds: bool = False,
    per_property_concrete_spec_name: str | None = None,
) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    holds = sum(1 for r in rows if r["result"] == "HOLDS")
    violated = sum(1 for r in rows if r["result"] == "VIOLATED")
    unknown = sum(1 for r in rows if r["result"] == "UNKNOWN")
    should_fail_violated = sum(1 for r in rows if "_ShouldFail" in r["property"] and r["result"] == "VIOLATED")
    should_fail_holds = [r["property"] for r in rows if "_ShouldFail" in r["property"] and r["result"] == "HOLDS"]
    should_fail_unknown = [r["property"] for r in rows if "_ShouldFail" in r["property"] and r["result"] == "UNKNOWN"]

    if use_all_strategies:
        header_note = (
            f"**K computation:** best of strict / path-depth / relaxed per property, "
            f"`dependency_mode={dependency_mode}`. Only properties with best K < {max_k}. Fallback to baseline when minimal yields VIOLATED (up to K ≤ {MAX_FALLBACK_K})."
            + (" **Confirm _ShouldFail:** baseline fallback also run for _ShouldFail properties." if confirm_shouldfail else " _ShouldFail properties do not fall back (use `--confirm-shouldfail` to confirm).")
        )
        if per_class_heuristic_confirm:
            header_note += " **Per-class heuristic:** run per-class-bounds first, then confirm HOLDS with strict encoding."
            if strict_per_class_bounds:
                header_note += " Strict confirm uses per-class bounds."
            else:
                header_note += " Strict confirm uses global K (theorem-complete)."
        table_header = "| Spec | Property | K | Strategy | Bound used | Result | Time (ms) | Complete |"
        table_sep = "|------|----------|---|----------|------------|--------|-----------|----------|"
    else:
        if smoke:
            fallback_note = f"**Smoke run:** only properties with K < {max_k}; no fallback to baseline when VIOLATED."
        else:
            fallback_note = (
                "Fallback to baseline fragment when minimal yields VIOLATED (up to K ≤ 250)."
                + (" **Confirm _ShouldFail:** baseline fallback also for _ShouldFail." if confirm_shouldfail else " _ShouldFail: no fallback (use `--confirm-shouldfail` to confirm).")
            )
        header_note = f"**K computation:** minimal fragment + `dependency_mode={dependency_mode}`. {fallback_note}"
        table_header = "| Spec | Property | K | Bound used | Result | Time (ms) | Complete |"
        table_sep = "|------|----------|---|------------|--------|-----------|----------|"

    lines = [
        "# Property Proof Results",
        "",
        f"Generated by `run_cegar.py` for **{spec_name}**.",
        "",
    ]
    if per_property_concrete_spec_name:
        lines.extend(
            [
                f"**Per-property abstraction:** each property is abstracted just-in-time from concrete spec `{Path(per_property_concrete_spec_name).name}` using `synthesize_abstract_spec_for_property(...)`.",
                "",
            ]
        )
    lines.extend([
        header_note,
        "",
        table_header,
        table_sep,
    ])
    for r in rows:
        k = r.get("K") if r.get("K") is not None else "-"
        complete_cell = r["is_complete"]
        if use_all_strategies:
            strategy = r.get("strategy", "-")
            lines.append(
                f"| {r['spec']} | {r['property']} | {k} | {strategy} | {r['bound_used']} | {r['result']} | {r['time_ms']} | {complete_cell} |"
            )
        else:
            lines.append(
                f"| {r['spec']} | {r['property']} | {k} | {r['bound_used']} | {r['result']} | {r['time_ms']} | {complete_cell} |"
            )
    lines.extend([
        "",
        "---",
        "",
        "## Summary",
        "",
        f"- **Total properties verified:** {len(rows)}.",
        f"- **HOLDS:** {holds}",
        f"- **VIOLATED:** {violated}",
        f"- **UNKNOWN:** {unknown}",
        "",
        "### Expected vs actual (diagnostic / _ShouldFail properties)",
        "",
        f"- Properties with `_ShouldFail` in the name are *intended* to be **VIOLATED** (the transformation correctly does not satisfy them).",
        f"- Among these, **{should_fail_violated}** reported VIOLATED (expected).",
    ])
    if should_fail_holds:
        lines.append(f"- **Suspicious (expected VIOLATED, got HOLDS):** {', '.join(should_fail_holds)}")
    if should_fail_unknown:
        lines.append(f"- **Inconclusive (expected VIOLATED, got UNKNOWN):** {', '.join(should_fail_unknown)}")
    lines.extend([
        "",
        "## Level of correctness achieved",
        "",
        "The property proof establishes the following for this transformation fragment:",
        "",
        "- **Structural correctness:** Core mapping properties proved **HOLDS** at computed K indicate expected target structure is preserved for the fragment.",
        "- **Attribute-aware correctness:** Attribute-constrained properties use the same K/tactic pipeline; HOLDS indicates consistency between encoding and intended semantics.",
        "- **Negative checks:** `_ShouldFail` properties that report **VIOLATED** confirm invalid postconditions are correctly rejected by the transformation+encoding.",
        "- **Limitations:** UNKNOWN results indicate timeout or solver resource limits at the chosen K; they do not disprove the property. Fallback to a larger fragment/K was applied when minimal fragment yielded VIOLATED to reduce spurious counterexamples.",
        "- **Complete column:** True indicates a definitive verdict—for **HOLDS**, verification was theorem-complete at the bound; for **VIOLATED**, a concrete counterexample was found.",
        "",
        "## Suspicious results (attribute-based K or encoding)",
        "",
    ])
    if should_fail_holds:
        lines.append("- **HOLDS on _ShouldFail:** A property expected to fail reported HOLDS. This may indicate an unsound K, missing dependency/trace coverage, or an encoding issue.")
    else:
        lines.append("- None: all _ShouldFail properties that were decided reported VIOLATED or UNKNOWN.")
    if unknown > 0:
        lines.append(f"- **UNKNOWN ({unknown}):** Inconclusive due to timeout or solver limit. Re-run with longer timeout or inspect K for those properties.")
    if per_property_concrete_spec_name:
        concrete_name = Path(per_property_concrete_spec_name).name
        if use_all_strategies:
            regen_cmd = f"python run_cegar.py --per-property-concrete-spec {concrete_name} --all-strategies --max-k {max_k} [--timeout 0]"
        elif smoke:
            regen_cmd = f"python run_cegar.py --per-property-concrete-spec {concrete_name} --smoke --max-k {max_k}"
        else:
            regen_cmd = f"python run_cegar.py --per-property-concrete-spec {concrete_name} [--timeout 0] [--dependency-mode trace_attr_aware]"
    else:
        if use_all_strategies:
            regen_cmd = f"python run_cegar.py --spec {spec_name} --all-strategies --max-k {max_k} [--timeout 0]"
        elif smoke:
            regen_cmd = f"python run_cegar.py --spec {spec_name} --smoke --max-k {max_k}"
        else:
            regen_cmd = f"python run_cegar.py --spec {spec_name} [--timeout 0] [--dependency-mode trace_attr_aware]"
    if confirm_shouldfail:
        regen_cmd += " --confirm-shouldfail"
    if per_class_heuristic_confirm:
        regen_cmd += " --per-class-heuristic-confirm"
    if strict_per_class_bounds:
        regen_cmd += " --strict-per-class-bounds"
    lines.extend([
        "",
        "## Configurability",
        "",
        "- **`--confirm-shouldfail`:** By default, properties whose name contains `_ShouldFail` do *not* run baseline fallback when minimal fragment yields VIOLATED (expected result; saves time). Use this flag to run baseline confirmation for _ShouldFail as well: if minimal says VIOLATED but baseline says HOLDS at higher K, that indicates a potential transformation or property issue and is worth investigating.",
        "- **`--per-class-heuristic-confirm`:** Two-phase mode: fast per-class pass first, then confirm HOLDS with a strict pass. VIOLATED from the first pass is already sound.",
        "- **`--strict-per-class-bounds`:** When used with `--per-class-heuristic-confirm`, the strict confirm pass also uses per-class bounds. Without this flag, strict pass uses global K.",
        "",
        "## How to regenerate",
        "",
        "From the **symbolic-execution-engine** directory:",
        "",
        "```bash",
        regen_cmd,
        "```",
        "",
    ])
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=0, help="Timeout per property in ms (0 = no timeout)")
    parser.add_argument(
        "--dependency-mode",
        choices=["legacy", "trace_aware", "trace_attr_aware"],
        default="trace_attr_aware",
        help="K computation mode",
    )
    parser.add_argument(
        "--spec",
        type=str,
        default=DEFAULT_SPEC,
        help="Spec file to run",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Optional output markdown path. Default: docs/<spec_stem>_proof_results.md",
    )
    parser.add_argument(
        "--properties",
        nargs="*",
        metavar="NAME",
        help="Only run these properties (e.g. ClassMapsToTable PKTracedFromClass). Default: all.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Smoke test: only properties with K < max_k; no fallback to baseline when VIOLATED.",
    )
    parser.add_argument(
        "--max-k",
        type=int,
        default=90,
        metavar="N",
        help="In smoke mode or --all-strategies, only run properties with K < N (default 90; use 100 for all strategies).",
    )
    parser.add_argument(
        "--all-strategies",
        action="store_true",
        help="Use best of strict / path-depth / relaxed per property; run only properties with best K < max-k, sorted by K ascending.",
    )
    parser.add_argument(
        "--confirm-shouldfail",
        action="store_true",
        help="When minimal yields VIOLATED, also run baseline fallback for _ShouldFail properties (audit mode; can be slow).",
    )
    parser.add_argument(
        "--per-class-heuristic-confirm",
        action="store_true",
        help="Run fast per-class-bounds pass, then confirm HOLDS with strict encoding (quick discharge of VIOLATED).",
    )
    parser.add_argument(
        "--strict-per-class-bounds",
        action="store_true",
        help="Use per-class bounds also in the strict confirm pass.",
    )
    parser.add_argument(
        "--per-property-concrete-spec",
        type=str,
        default=None,
        help="Concrete spec in examples/ to abstract per property just before proving while keeping the run_cegar verification flow.",
    )
    args = parser.parse_args()
    if args.all_strategies:
        mode = f"all-strategies K<{args.max_k}"
    else:
        mode = f"smoke K<{args.max_k}" if args.smoke else "full"
    if args.per_class_heuristic_confirm:
        mode += "+per-class-confirm"
    if args.strict_per_class_bounds:
        mode += "+strict-per-class"
    display_spec = Path(args.per_property_concrete_spec or args.spec).name
    out_path = Path(args.out) if args.out else _default_report_path(display_spec)
    print(
        f"Running property proof ({display_spec}, {mode}, dependency_mode={args.dependency_mode})...",
        flush=True,
    )
    rows = run_proof(
        args.timeout,
        args.dependency_mode,
        property_filter=args.properties,
        smoke=args.smoke,
        max_k=args.max_k,
        use_all_strategies=args.all_strategies,
        confirm_shouldfail=args.confirm_shouldfail,
        per_class_heuristic_confirm=args.per_class_heuristic_confirm,
        strict_per_class_bounds=args.strict_per_class_bounds,
        spec_name=args.spec,
        per_property_concrete_spec_name=args.per_property_concrete_spec,
        out_path=out_path,
    )
    holds = sum(1 for r in rows if r["result"] == "HOLDS")
    violated = sum(1 for r in rows if r["result"] == "VIOLATED")
    unknown = sum(1 for r in rows if r["result"] == "UNKNOWN")
    print(f"Total: {len(rows)} | HOLDS: {holds} | VIOLATED: {violated} | UNKNOWN: {unknown}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
