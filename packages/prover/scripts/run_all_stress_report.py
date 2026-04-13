#!/usr/bin/env python3
"""
Run property verification for bpmn2petri_frag, persons_frag, class2relational_frag, uml2java_frag_v2
and write all results to docs/cutoff_stress_results.md.

All specs use: minimal fragment (minimal_satisfying_layer_indices), property slicing, metamodel slicing.
K is computed with compute_cutoff_bound(fragment, prop, dependency_mode=...). Default dependency_mode
is trace_aware (trace-aware relevance/dependency for smaller K). Falls back to baseline fragment if
minimal yields VIOLATED.

Usage: python run_all_stress_report.py [--timeout 600000] [--dependency-mode trace_aware]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dsltrans.parser import parse_dsltrans_file
from dsltrans.cutoff import check_fragment, build_fragment, get_relevant_rules, layer_indices_for_rules, minimal_satisfying_layer_indices, compute_cutoff_bound
from dsltrans.smt_direct import SMTDirectConfig, SMTDirectVerifier

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "evaluation"
OUT_PATH = DOCS_DIR / "cutoff_stress_results.md"

SPECS_CUTOFF = [
    "bpmn2petri_concrete.dslt",
    "persons_concrete.dslt",
    "class2relational_concrete.dslt",
    "class2relational_concrete.dslt",
    "uml2java_frag_v2.dslt",
    "uml2java_concrete_canonical.dslt",
    "atlcompiler_concrete.dslt",
    "oclcompiler_concrete.dslt",
    "ecore2jsonschema_concrete.dslt",
    "pnml2nupn_concrete.dslt",
]


def _stats_dict(res) -> dict[str, float | int | bool | str]:
    stats = getattr(res, "stats", None)
    if stats is None:
        return {
            "encoding_ms": 0.0,
            "relevance_ms": 0.0,
            "string_reduction_ms": 0.0,
            "metamodel_slice_ms": 0.0,
            "per_class_bounds_ms": 0.0,
            "model_encoder_ms": 0.0,
            "rule_encoder_ms": 0.0,
            "property_encoder_ms": 0.0,
            "check_ms": 0.0,
            "refinement_ms": 0.0,
            "solver_calls": 0,
            "refinement_model_inspections": 0,
            "refinement_rounds": 0,
            "refinement_clauses": 0,
            "refined_target_nodes": 0,
            "refined_target_links": 0,
            "pre_bindings": 0,
            "violation_count": 0,
            "post_components": 0,
            "post_component_bindings": 0,
            "post_full_bindings": 0,
            "used_factored_post": False,
            "incremental_candidates_total": 0,
            "incremental_candidates_checked": 0,
            "incremental_candidates_unsat": 0,
            "incremental_candidates_sat": 0,
            "incremental_candidates_unknown": 0,
            "phase": "",
            "exception_phase": "",
            "auto_incremental_fallback_suggested": False,
            "auto_incremental_fallback_used": False,
            "auto_incremental_fallback_reason": "",
        }
    return {
        "encoding_ms": round(float(getattr(stats, "encoding_ms", 0.0)), 1),
        "relevance_ms": round(float(getattr(stats, "relevance_ms", 0.0)), 1),
        "string_reduction_ms": round(float(getattr(stats, "string_reduction_ms", 0.0)), 1),
        "metamodel_slice_ms": round(float(getattr(stats, "metamodel_slice_ms", 0.0)), 1),
        "per_class_bounds_ms": round(float(getattr(stats, "per_class_bounds_ms", 0.0)), 1),
        "model_encoder_ms": round(float(getattr(stats, "model_encoder_ms", 0.0)), 1),
        "rule_encoder_ms": round(float(getattr(stats, "rule_encoder_ms", 0.0)), 1),
        "property_encoder_ms": round(float(getattr(stats, "property_encoder_ms", 0.0)), 1),
        "check_ms": round(float(getattr(stats, "check_ms", 0.0)), 1),
        "refinement_ms": round(float(getattr(stats, "refinement_ms", 0.0)), 1),
        "solver_calls": int(getattr(stats, "solver_calls", 0)),
        "refinement_model_inspections": int(getattr(stats, "refinement_model_inspections", 0)),
        "refinement_rounds": int(getattr(stats, "refinement_rounds", 0)),
        "refinement_clauses": int(getattr(stats, "refinement_clauses", 0)),
        "refined_target_nodes": int(getattr(stats, "refined_target_nodes", 0)),
        "refined_target_links": int(getattr(stats, "refined_target_links", 0)),
        "pre_bindings": int(getattr(stats, "pre_bindings", 0)),
        "violation_count": int(getattr(stats, "violation_count", 0)),
        "post_components": int(getattr(stats, "post_components", 0)),
        "post_component_bindings": int(getattr(stats, "post_component_bindings", 0)),
        "post_full_bindings": int(getattr(stats, "post_full_bindings", 0)),
        "used_factored_post": bool(getattr(stats, "used_factored_post", False)),
        "incremental_candidates_total": int(getattr(stats, "incremental_candidates_total", 0)),
        "incremental_candidates_checked": int(getattr(stats, "incremental_candidates_checked", 0)),
        "incremental_candidates_unsat": int(getattr(stats, "incremental_candidates_unsat", 0)),
        "incremental_candidates_sat": int(getattr(stats, "incremental_candidates_sat", 0)),
        "incremental_candidates_unknown": int(getattr(stats, "incremental_candidates_unknown", 0)),
        "phase": str(getattr(stats, "phase", "")),
        "exception_phase": str(getattr(stats, "exception_phase", "")),
        "auto_incremental_fallback_suggested": bool(getattr(stats, "auto_incremental_fallback_suggested", False)),
        "auto_incremental_fallback_used": bool(getattr(stats, "auto_incremental_fallback_used", False)),
        "auto_incremental_fallback_reason": str(getattr(stats, "auto_incremental_fallback_reason", "")),
    }


def _verify_with_fragment(
    spec,
    prop,
    fragment_trans,
    K,
    timeout_ms,
    dependency_mode="trace_aware",
    proof_mode="strict_theorem",
):
    """Build a fragment spec and verify a single property."""
    frag_spec = type(spec)(
        metamodels=spec.metamodels,
        transformations=(fragment_trans,),
        properties=(prop,),
    )
    config = SMTDirectConfig(
        bound=K,
        use_cutoff=True,
        timeout_ms=timeout_ms if timeout_ms > 0 else None,
        use_property_slicing=True,
        use_metamodel_slicing=True,
        use_per_class_type_bounds=True,
        per_class_bounds_analysis="fixed_point",
        per_class_bound_mode=proof_mode,
        dependency_mode=dependency_mode,
    )
    verifier = SMTDirectVerifier(frag_spec, config)
    return verifier.verify_property(prop)


def run_cutoff_specs(
    timeout_ms: int,
    all_rows: list[dict],
    write_cb=None,
    specs_filter: list[str] | None = None,
    dependency_mode: str = "trace_aware",
    proof_mode: str = "strict_theorem",
) -> list[dict]:
    """
    Run verification for all four fragment specs.

    Uses trace-aware minimal fragment (minimal_satisfying_layer_indices) and
    K = compute_cutoff_bound(fragment, prop, dependency_mode=dependency_mode).
    By monotonicity, HOLDS in a fragment implies HOLDS for the full transformation.
    If the minimal fragment yields VIOLATED, falls back to baseline fragment when feasible.
    """
    specs_to_run = SPECS_CUTOFF
    if specs_filter is not None:
        specs_to_run = [s for s in SPECS_CUTOFF if s in specs_filter]
    for spec_name in specs_to_run:
        path = EXAMPLES_DIR / spec_name
        if not path.exists():
            print(f"  Skip (not found): {spec_name}", flush=True)
            continue
        try:
            spec = parse_dsltrans_file(path)
            if not spec.transformations or not spec.properties:
                continue
            full_trans = spec.transformations[0]
            for prop in spec.properties:
                in_frag, _ = check_fragment(full_trans, prop)
                if not in_frag:
                    continue

                # Step 1: trace-aware minimal fragment, K with chosen dependency_mode
                min_layers = minimal_satisfying_layer_indices(full_trans, prop)
                min_frag = build_fragment(full_trans, min_layers)
                K_min = compute_cutoff_bound(min_frag, prop, use_reduced_k=True, dependency_mode=dependency_mode)

                # Baseline layers for fallback
                baseline_layers = layer_indices_for_rules(
                    full_trans, get_relevant_rules(full_trans, prop)
                )

                print(f"  {spec_name} / {prop.name} (K={K_min} layers {min_layers}) ... ", end="", flush=True)
                res = _verify_with_fragment(
                    spec,
                    prop,
                    min_frag,
                    K_min,
                    timeout_ms,
                    dependency_mode=dependency_mode,
                    proof_mode=proof_mode,
                )

                # Step 2: if VIOLATED and minimal != baseline, fall back to baseline when feasible
                MAX_FALLBACK_K = 250  # skip fallback when baseline K would be impractically large
                if (
                    res.result.name == "VIOLATED"
                    and min_layers != baseline_layers
                    and not prop.name.endswith("_ShouldFail")
                ):
                    baseline_frag = build_fragment(full_trans, baseline_layers)
                    K_base = compute_cutoff_bound(baseline_frag, prop, use_reduced_k=True, dependency_mode=dependency_mode)
                    if K_base <= MAX_FALLBACK_K:
                        print(f"VIOLATED; fallback K={K_base} layers {baseline_layers} ... ", end="", flush=True)
                        res = _verify_with_fragment(
                            spec,
                            prop,
                            baseline_frag,
                            K_base,
                            timeout_ms,
                            dependency_mode=dependency_mode,
                            proof_mode=proof_mode,
                        )
                        K_min = K_base
                    else:
                        print(f"VIOLATED (baseline K={K_base} skipped) ", end="", flush=True)

                row = {
                    "spec": spec_name,
                    "property": prop.name,
                    "K": K_min,
                    "bound_used": res.bound_used,
                    "result": res.result.name,
                    "time_ms": round(res.time_ms, 1),
                    "is_complete": res.is_complete,
                    "dependency_mode": dependency_mode,
                    "message": res.message,
                }
                row.update(_stats_dict(res))
                all_rows.append(row)
                print(f"{res.result.name} ({res.time_ms:.0f} ms)", flush=True)
                if write_cb:
                    write_cb()
        except Exception as e:
            all_rows.append({
                "spec": spec_name,
                "property": "(error)",
                "K": None,
                "bound_used": 0,
                "result": "UNKNOWN",
                "time_ms": 0,
                "is_complete": False,
                "message": str(e),
                "encoding_ms": 0.0,
                "relevance_ms": 0.0,
                "string_reduction_ms": 0.0,
                "metamodel_slice_ms": 0.0,
                "per_class_bounds_ms": 0.0,
                "model_encoder_ms": 0.0,
                "rule_encoder_ms": 0.0,
                "property_encoder_ms": 0.0,
                "check_ms": 0.0,
                "refinement_ms": 0.0,
                "solver_calls": 0,
                "refinement_model_inspections": 0,
                "refinement_rounds": 0,
                "refinement_clauses": 0,
                "refined_target_nodes": 0,
                "refined_target_links": 0,
                "pre_bindings": 0,
                "violation_count": 0,
                "post_components": 0,
                "post_component_bindings": 0,
                "post_full_bindings": 0,
                "used_factored_post": False,
                "incremental_candidates_total": 0,
                "incremental_candidates_checked": 0,
                "incremental_candidates_unsat": 0,
                "incremental_candidates_sat": 0,
                "incremental_candidates_unknown": 0,
                "phase": "",
                "exception_phase": "",
                "auto_incremental_fallback_suggested": False,
                "auto_incremental_fallback_used": False,
                "auto_incremental_fallback_reason": "",
            })
            print(f"  {spec_name}: ERROR {e}", flush=True)
            if write_cb:
                write_cb()


def write_results_md(
    rows: list[dict],
    dependency_mode: str = "trace_aware",
    proof_mode: str = "strict_theorem",
    out_path: Path | None = None,
) -> None:
    path = out_path or OUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Cutoff-Style Stress Test Results",
        "",
        "Generated by `run_all_stress_report.py`.",
        "These runs combine property-directed fragments with the selected dependency mode.",
        f"**Proof mode:** `{proof_mode}`.",
        "Rows with `Complete=False` are empirical bounded checks, not theorem-complete proofs.",
        "",
        f"**K computation:** minimal fragment + `dependency_mode={dependency_mode}` (trace-aware relevance/dependency for smaller K).",
        "",
        "| Spec | Property | K | Bound used | Result | Time (ms) | Encode (ms) | Encode detail | Bindings | Incremental candidates | Check (ms) | Refine (ms) | Solver calls | Refine scans | Refine rounds | Refine clauses | Refined targets | Complete | Notes |",
        "|------|----------|---|------------|--------|-----------|-------------|---------------|----------|------------------------|------------|-------------|--------------|--------------|---------------|----------------|-----------------|----------|-------|",
    ]
    for r in rows:
        k = r.get("K") if r.get("K") is not None else "-"
        note = ""
        if r.get("result") == "UNKNOWN":
            note = r.get("message") or "solver returned UNKNOWN"
        elif not r.get("is_complete", False):
            note = r.get("message") or "bounded/incomplete run"
        else:
            note = "theorem-complete at reported bound"
        if r.get("auto_incremental_fallback_used", False):
            reason = r.get("auto_incremental_fallback_reason") or "dangerous encoding shape"
            note = f"{note}; auto incremental fallback ({reason})"
        if r.get("exception_phase"):
            note = f"{note}; exception_phase={r['exception_phase']}"
        encode_detail = (
            f"rel={r.get('relevance_ms', 0.0)}, mm={r.get('metamodel_slice_ms', 0.0)}, "
            f"bnd={r.get('per_class_bounds_ms', 0.0)}, mdl={r.get('model_encoder_ms', 0.0)}, "
            f"rules={r.get('rule_encoder_ms', 0.0)}, prop={r.get('property_encoder_ms', 0.0)}"
        )
        bindings = (
            f"pre={r.get('pre_bindings', 0)}, viol={r.get('violation_count', 0)}, "
            f"comp={r.get('post_components', 0)}, cb={r.get('post_component_bindings', 0)}, "
            f"pb={r.get('post_full_bindings', 0)}, fact={r.get('used_factored_post', False)}"
        )
        incremental = (
            f"checked={r.get('incremental_candidates_checked', 0)}/{r.get('incremental_candidates_total', 0)}, "
            f"sat={r.get('incremental_candidates_sat', 0)}, "
            f"unsat={r.get('incremental_candidates_unsat', 0)}, "
            f"unk={r.get('incremental_candidates_unknown', 0)}"
        )
        refined_targets = f"n={r.get('refined_target_nodes', 0)}, l={r.get('refined_target_links', 0)}"
        lines.append(
            f"| {r['spec']} | {r['property']} | {k} | {r['bound_used']} | {r['result']} | {r['time_ms']} | {r.get('encoding_ms', 0.0)} | {encode_detail} | {bindings} | {incremental} | {r.get('check_ms', 0.0)} | {r.get('refinement_ms', 0.0)} | {r.get('solver_calls', 0)} | {r.get('refinement_model_inspections', 0)} | {r.get('refinement_rounds', 0)} | {r.get('refinement_clauses', 0)} | {refined_targets} | {r['is_complete']} | {note} |"
        )
    lines.extend(["", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {path}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=600_000, help="Timeout per property in ms (0 = no timeout)")
    parser.add_argument(
        "--dependency-mode",
        choices=["legacy", "trace_aware", "trace_attr_aware"],
        default="trace_aware",
        help="Relevance/dependency mode for K computation (trace_aware yields smaller K for uml2java).",
    )
    parser.add_argument(
        "--specs",
        nargs="*",
        default=None,
        help="Only run these spec files (e.g. bpmn2petri_concrete.dslt persons_concrete.dslt). Default: all.",
    )
    parser.add_argument(
        "--proof-mode",
        choices=["strict_theorem", "aggressive_optimized"],
        default="strict_theorem",
        help="Use theorem-complete per-class bounds or the existing aggressive optimized mode.",
    )
    parser.add_argument("--out", type=str, default=None, help="Output markdown path. Default: docs/evaluation/cutoff_stress_results.md")
    args = parser.parse_args()

    all_rows = []
    specs_filter = args.specs
    dependency_mode = args.dependency_mode
    proof_mode = args.proof_mode
    out_path = Path(args.out) if args.out else None

    def write_cb():
        write_results_md(
            all_rows,
            dependency_mode=dependency_mode,
            proof_mode=proof_mode,
            out_path=out_path,
        )

    print(
        f"Running cutoff-style verification (all specs, dependency_mode={dependency_mode}, proof_mode={proof_mode})...",
        flush=True,
    )
    run_cutoff_specs(
        args.timeout,
        all_rows,
        write_cb=write_cb,
        specs_filter=specs_filter,
        dependency_mode=dependency_mode,
        proof_mode=proof_mode,
    )

    write_results_md(
        all_rows,
        dependency_mode=dependency_mode,
        proof_mode=proof_mode,
        out_path=out_path,
    )

    holds = sum(1 for r in all_rows if r["result"] == "HOLDS")
    violated = sum(1 for r in all_rows if r["result"] == "VIOLATED")
    unknown = sum(1 for r in all_rows if r["result"] == "UNKNOWN")
    print(f"Total: {len(all_rows)} | HOLDS: {holds} | VIOLATED: {violated} | UNKNOWN: {unknown}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
