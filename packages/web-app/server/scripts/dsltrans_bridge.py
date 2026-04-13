"""
Bridge script for dsltrans-web-app: delegates to dsltrans-prover for parse,
concrete execution, symbolic verification, cutoff, and fragment validation.
Expects PYTHONPATH to include dsltrans-prover/src so "dsltrans" is importable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from dsltrans.parser import parse_dsltrans
from dsltrans.cutoff import check_fragment, compute_cutoff_bound
from dsltrans.runtime_engine import execute_transformation
from dsltrans.smt_direct import SMTDirectConfig, SMTDirectVerifier
from dsltrans.xmi_io import load_xmi_model, save_xmi_model
from dsltrans.concrete_property_checker import check_properties_concrete
from dsltrans.model import Property
from dsltrans.abstraction import (
    AbstractionPolicy,
    make_default_abstraction_policy,
    synthesize_abstract_spec_for_property,
)

# Reuse the same hybrid verification entrypoint used in stress runs.
_PROVER_SCRIPTS = Path.cwd() / "scripts"
if str(_PROVER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PROVER_SCRIPTS))
from run_hybrid_cegar_stress import verify_property_hybrid

DEFAULT_FALLBACK_K_CAP = 250
AUTO_APPROVED_FALLBACK_K_CAPS = (250, 400, 600)
_CAP_LIMIT_RE = re.compile(r"baseline confirmation requires K=(\d+) > cap (\d+)")


def _read_payload() -> dict:
    return json.load(fp=getattr(__import__("sys"), "stdin"))


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _metamodel_to_json(mm) -> dict:
    def _mult_tuple_to_list(mult):
        lo, hi = mult
        return [int(lo), None if hi is None else int(hi)]

    return {
        "name": mm.name,
        "classes": [
            {
                "id": str(c.id),
                "name": c.name,
                "isAbstract": bool(c.is_abstract),
                "parent": str(c.parent) if c.parent is not None else None,
                "attributes": [
                    {
                        "name": a.name,
                        "type": a.type,
                        "default": a.default,
                        "intRange": list(a.int_range) if a.int_range is not None else None,
                        "stringVocab": list(a.string_vocab),
                    }
                    for a in c.attributes
                ],
            }
            for c in mm.classes
        ],
        "associations": [
            {
                "id": str(a.id),
                "name": a.name,
                "sourceClass": str(a.source_class),
                "targetClass": str(a.target_class),
                "sourceMult": _mult_tuple_to_list(a.source_mult),
                "targetMult": _mult_tuple_to_list(a.target_mult),
                "isContainment": bool(a.is_containment),
            }
            for a in mm.associations
        ],
        "enums": [
            {"name": e.name, "literals": list(e.literals)}
            for e in mm.enums
        ],
    }


def _ensure_single_transformation(spec):
    if not spec.transformations:
        raise ValueError("No transformation found in specification")
    return spec.transformations[0]


def _cap_limited_unknown_required_k(result: dict) -> int | None:
    if result.get("result") != "UNKNOWN":
        return None
    message = str(result.get("message", ""))
    match = _CAP_LIMIT_RE.search(message)
    if not match:
        return None
    return int(match.group(1))


def _resolved_fallback_caps(payload: dict) -> tuple[int, ...]:
    raw_caps = payload.get("autoFallbackKCaps")
    if isinstance(raw_caps, list) and raw_caps:
        caps = [int(v) for v in raw_caps]
    else:
        caps = list(AUTO_APPROVED_FALLBACK_K_CAPS)
    caps = sorted(set(v for v in caps if v > 0))
    if not caps:
        caps = list(AUTO_APPROVED_FALLBACK_K_CAPS)
    return tuple(caps)


def _run_hybrid_with_cap_retries(
    spec,
    prop,
    *,
    dependency_mode: str,
    timeout_ms: int,
    payload: dict,
    abstraction_policy: AbstractionPolicy | None = None,
) -> dict:
    caps = _resolved_fallback_caps(payload)
    attempts = []
    final_result = None

    for cap in caps:
        hybrid = verify_property_hybrid(
            spec,
            prop,
            dependency_mode=dependency_mode,
            timeout_ms=timeout_ms,
            fallback_k_cap=cap,
            abstraction_policy=abstraction_policy,
        )
        attempts.append(cap)
        final_result = hybrid
        required_k = _cap_limited_unknown_required_k(hybrid)
        if required_k is None or required_k <= cap:
            break
        if cap >= caps[-1]:
            break

    assert final_result is not None
    required_k = _cap_limited_unknown_required_k(final_result)
    if required_k is not None and attempts and attempts[-1] < required_k:
        prior = final_result.get("message", "")
        approval_note = (
            f" Web app auto-retried fallback caps up to {attempts[-1]}; "
            f"confirming this property would require a higher cap ({required_k}) and explicit approval."
        )
        final_result = {**final_result, "message": f"{prior}{approval_note}".strip()}

    return {
        **final_result,
        "fallback_k_cap_used": attempts[-1] if attempts else DEFAULT_FALLBACK_K_CAP,
        "fallback_k_cap_attempts": attempts,
    }


def _run_concrete(payload: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        spec_path = base / "spec.dslt"
        in_path = base / "input.xmi"
        out_path = base / "output.xmi"
        _write_text(spec_path, payload["specText"])
        _write_text(in_path, payload["inputXmi"])

        spec = parse_dsltrans(payload["specText"])
        trans = _ensure_single_transformation(spec)
        source_model = load_xmi_model(in_path, trans.source_metamodel)
        target_model, stats = execute_transformation(trans, source_model)
        save_xmi_model(out_path, target_model, trans.target_metamodel.name)
        property_results = check_properties_concrete(
            transformation=trans,
            source_model=source_model,
            target_model=target_model,
            traces=target_model.traces,
            properties=spec.properties,
        )
        return {
            "mode": "concrete",
            "stats": {
                "created_nodes": stats.created_nodes,
                "created_edges": stats.created_edges,
                "created_traces": stats.created_traces,
            },
            "propertyResults": [
                {
                    "id": r.property_id,
                    "name": r.property_name,
                    "status": r.status,
                    "checked_pre_matches": r.checked_pre_matches,
                }
                for r in property_results
            ],
            "outputXmi": out_path.read_text(encoding="utf-8"),
        }


def _run_explore(payload: dict) -> dict:
    """Symbolic explore: use prover verify_direct and return compatible shape (no path-condition enumeration)."""
    spec = parse_dsltrans(payload["specText"])
    trans = _ensure_single_transformation(spec)
    config = SMTDirectConfig(
        bound=int(payload.get("bound", 5)),
        timeout_ms=int(payload.get("timeoutMs", 60000)),
        use_cutoff=bool(payload.get("useCutoff", True)),
    )
    verifier = SMTDirectVerifier(spec, config)
    direct_result = verifier.verify_all()
    return {
        "mode": "explore",
        "pathConditions": 0,
        "propertyResults": [pr.result.name.lower() for pr in direct_result.property_results],
        "stats": {
            "holds_count": direct_result.holds_count,
            "violated_count": direct_result.violated_count,
            "unknown_count": direct_result.unknown_count,
            "total_time_ms": direct_result.total_time_ms,
        },
    }


def _run_smt_direct(payload: dict) -> dict:
    spec, prep_meta, abstraction_policy = _prepare_spec_for_proof(payload)
    trans = _ensure_single_transformation(spec)
    if abstraction_policy is None:
        # Server-side fragment enforcement only applies directly when no
        # per-property concrete-to-proof abstraction is needed.
        for prop in spec.properties:
            if isinstance(prop, Property):
                in_frag, violations = check_fragment(trans, prop)
                if not in_frag:
                    msg = "; ".join(v.reason for v in violations[:5])
                    raise ValueError(
                        f"Prover only accepts in-fragment specs. Property {prop.name!r} is outside the verifiable fragment: {msg}"
                    )

    timeout_ms = int(payload.get("timeoutMs", 180000))
    dependency_mode = str(payload.get("dependencyMode", "trace_attr_aware"))
    rows = []
    for prop in spec.properties:
        hybrid = _run_hybrid_with_cap_retries(
            spec,
            prop,
            dependency_mode=dependency_mode,
            timeout_ms=timeout_ms,
            payload=payload,
            abstraction_policy=abstraction_policy,
        )
        if hybrid.get("skipped"):
            violations = hybrid.get("fragment_violations", [])
            reason = hybrid.get("skip_reason", "not_in_fragment")
            msg = "; ".join(str(v) for v in violations) if violations else reason
            raise ValueError(
                f"Prover only accepts in-fragment specs. Property {prop.name!r} "
                f"is outside the verifiable fragment: {msg}"
            )
        rows.append(
            {
                "property": hybrid["property"],
                "result": hybrid["result"],
                "K": hybrid.get("K"),
                "bound_used": hybrid["bound_used"],
                "is_complete": hybrid["is_complete"],
                "cegar_iters": hybrid.get("cegar_iters", 0),
                "time_ms": hybrid["time_ms"],
                "message": hybrid.get("message", ""),
                "fallback_k_cap_used": hybrid.get("fallback_k_cap_used"),
                "fallback_k_cap_attempts": hybrid.get("fallback_k_cap_attempts", []),
            }
        )
    return {"mode": "hybrid", "results": rows, "proofPreparation": prep_meta}


def _run_smt_direct_stream(payload: dict) -> None:
    spec, prep_meta, abstraction_policy = _prepare_spec_for_proof(payload)
    trans = _ensure_single_transformation(spec)
    if abstraction_policy is None:
        for prop in spec.properties:
            if isinstance(prop, Property):
                in_frag, violations = check_fragment(trans, prop)
                if not in_frag:
                    msg = "; ".join(v.reason for v in violations[:5])
                    raise ValueError(
                        f"Prover only accepts in-fragment specs. Property {prop.name!r} is outside the verifiable fragment: {msg}"
                    )

    timeout_ms = int(payload.get("timeoutMs", 180000))
    dependency_mode = str(payload.get("dependencyMode", "trace_attr_aware"))
    total = len(spec.properties)
    rows = []
    print(json.dumps({"event": "start", "mode": "hybrid", "total": total, "proofPreparation": prep_meta}), flush=True)

    for idx, prop in enumerate(spec.properties, start=1):
        hybrid = _run_hybrid_with_cap_retries(
            spec,
            prop,
            dependency_mode=dependency_mode,
            timeout_ms=timeout_ms,
            payload=payload,
            abstraction_policy=abstraction_policy,
        )
        if hybrid.get("skipped"):
            violations = hybrid.get("fragment_violations", [])
            reason = hybrid.get("skip_reason", "not_in_fragment")
            msg = "; ".join(str(v) for v in violations) if violations else reason
            raise ValueError(
                f"Prover only accepts in-fragment specs. Property {prop.name!r} "
                f"is outside the verifiable fragment: {msg}"
            )
        row = {
            "property": hybrid["property"],
            "result": hybrid["result"],
            "K": hybrid.get("K"),
            "bound_used": hybrid["bound_used"],
            "is_complete": hybrid["is_complete"],
            "cegar_iters": hybrid.get("cegar_iters", 0),
            "time_ms": hybrid["time_ms"],
            "message": hybrid.get("message", ""),
            "fallback_k_cap_used": hybrid.get("fallback_k_cap_used"),
            "fallback_k_cap_attempts": hybrid.get("fallback_k_cap_attempts", []),
        }
        rows.append(row)
        print(
            json.dumps(
                {
                    "event": "property_result",
                    "mode": "hybrid",
                    "completed": idx,
                    "remaining": total - idx,
                    "total": total,
                    "result": row,
                }
            ),
            flush=True,
        )

    print(
        json.dumps(
            {
                "event": "complete",
                "mode": "hybrid",
                "completed": total,
                "remaining": 0,
                "total": total,
                "results": rows,
                "proofPreparation": prep_meta,
            }
        ),
        flush=True,
    )


def _prepare_spec_for_proof(payload: dict):
    """
    Returns a fragment-valid spec for proof commands.
    If payload spec is out-of-fragment but appears concrete, auto-derive an
    abstract proof spec and use that for SMT-direct/hybrid verification.
    """
    spec = parse_dsltrans(payload["specText"])
    trans = _ensure_single_transformation(spec)
    violations_by_property: dict[str, list[str]] = {}
    needs_abstraction = False
    for prop in spec.properties:
        if not isinstance(prop, Property):
            continue
        in_frag, violations = check_fragment(trans, prop)
        if not in_frag:
            needs_abstraction = True
            violations_by_property[prop.name] = [v.reason for v in violations]

    if not needs_abstraction:
        return spec, {
            "applied": False,
            "reason": "input_spec_already_fragment_valid",
            "sourceTransformation": trans.name,
            "proofTransformation": trans.name,
            "violationsBeforeAbstraction": {},
        }, None

    policy = make_default_abstraction_policy(spec)
    policy_name = "generic_auto"

    proof_trans_name = policy.transformation_renames.get(trans.name, trans.name)
    for prop in spec.properties:
        if not isinstance(prop, Property):
            continue
        proof_spec = synthesize_abstract_spec_for_property(spec, policy, prop.name).abstract_spec
        proof_trans = _ensure_single_transformation(proof_spec)
        proof_prop = proof_spec.properties[0]
        in_frag, violations = check_fragment(proof_trans, proof_prop)
        if not in_frag:
            msg = "; ".join(v.reason for v in violations[:5]) if violations else "unknown"
            raise ValueError(
                "Automatic concrete-to-proof abstraction failed to produce a fragment-valid proof spec. "
                f"Property {prop.name!r} remains outside the fragment: {msg}"
            )

    return spec, {
        "applied": True,
        "policy": policy_name,
        "mode": "per_property",
        "reason": "auto_abstracted_non_fragment_input_for_proof",
        "sourceTransformation": trans.name,
        "proofTransformation": proof_trans_name,
        "violationsBeforeAbstraction": violations_by_property,
        "metamodelMapping": policy.metamodel_renames,
        "transformationMapping": policy.transformation_renames,
    }, policy


def _run_cutoff(payload: dict) -> dict:
    spec = parse_dsltrans(payload["specText"])
    trans = _ensure_single_transformation(spec)
    # Server-side: we still return per-property cutoff info; fragment check is advisory in this endpoint
    rows = []
    for prop in spec.properties:
        if isinstance(prop, Property):
            in_fragment, violations = check_fragment(trans, prop)
            rows.append(
                {
                    "property": prop.name,
                    "in_fragment": in_fragment,
                    "cutoff": compute_cutoff_bound(trans, prop) if in_fragment else None,
                    "violations": [v.rule_name or v.rule_id for v in violations],
                }
            )
        else:
            rows.append(
                {
                    "property": getattr(prop, "name", str(prop)),
                    "in_fragment": False,
                    "cutoff": None,
                    "violations": ["Composite property not checked for fragment"],
                }
            )
    return {"mode": "cutoff", "results": rows}


def _parse_only(payload: dict) -> dict:
    spec = parse_dsltrans(payload["specText"])
    return {
        "metamodels": [mm.name for mm in spec.metamodels],
        "transformations": [t.name for t in spec.transformations],
        "properties": [getattr(p, "name", str(p)) for p in spec.properties],
    }


def _validate_fragment(payload: dict) -> dict:
    spec = parse_dsltrans(payload["specText"])
    violations: list[str] = []
    checked_pairs = 0

    for trans in spec.transformations:
        for prop in spec.properties:
            if isinstance(prop, Property):
                in_fragment, errs = check_fragment(trans, prop)
                checked_pairs += 1
                if not in_fragment:
                    suffix = ",".join((v.rule_name or v.rule_id) for v in errs) if errs else "unknown"
                    violations.append(f"{trans.name}:{prop.name}:{suffix}")

    if checked_pairs == 0:
        violations.append("No transformation/property pairs found for fragment validation")

    out = {
        "loadable": len(violations) == 0,
        "violations": sorted(set(violations)),
        "transformationCount": len(spec.transformations),
        "propertyCount": len(spec.properties),
    }
    if spec.transformations:
        trans = spec.transformations[0]
        out["sourceMetamodel"] = trans.source_metamodel.name
        out["targetMetamodel"] = trans.target_metamodel.name
        out["sourceMetamodelDetail"] = _metamodel_to_json(trans.source_metamodel)
        out["targetMetamodelDetail"] = _metamodel_to_json(trans.target_metamodel)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--command",
        required=True,
        choices=["parse", "concrete", "explore", "smt_direct", "smt_direct_stream", "cutoff", "validate_fragment"],
    )
    args = parser.parse_args()
    payload = _read_payload()

    try:
        if args.command == "parse":
            out = _parse_only(payload)
        elif args.command == "concrete":
            out = _run_concrete(payload)
        elif args.command == "explore":
            spec = parse_dsltrans(payload["specText"])
            trans = _ensure_single_transformation(spec)
            for prop in spec.properties:
                if isinstance(prop, Property):
                    in_frag, _ = check_fragment(trans, prop)
                    if not in_frag:
                        raise ValueError(
                            f"Explore only accepts in-fragment specs. Property {prop.name!r} is outside the verifiable fragment."
                        )
            out = _run_explore(payload)
        elif args.command == "smt_direct":
            out = _run_smt_direct(payload)
        elif args.command == "smt_direct_stream":
            _run_smt_direct_stream(payload)
            return 0
        elif args.command == "validate_fragment":
            out = _validate_fragment(payload)
        else:
            out = _run_cutoff(payload)
    except ValueError as e:
        if args.command == "smt_direct_stream":
            print(json.dumps({"event": "error", "error": str(e), "errorKind": "fragment_or_validation"}))
        else:
            print(json.dumps({"error": str(e), "errorKind": "fragment_or_validation"}))
        return 1
    except Exception as e:
        if args.command == "smt_direct_stream":
            print(json.dumps({"event": "error", "error": str(e), "errorKind": "runtime"}))
        else:
            print(json.dumps({"error": str(e), "errorKind": "runtime"}))
        return 1

    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
