#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dsltrans.cutoff import compute_cutoff_bound_detailed, compute_per_class_slot_bounds_fixed_point
from dsltrans.parser import parse_dsltrans_file
from dsltrans.smt_direct import SMTDirectConfig, SMTDirectVerifier
import dsltrans.smt_direct as smt_direct

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = ROOT / "examples"
EVALUATION_DIR = ROOT / "docs" / "evaluation"
TMP_DIR = ROOT / "cross_validation_tmp" / "k_boundary"
TMP_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = EVALUATION_DIR / "k_boundary_expanded_results.md"
FORMULA_SURVEY_PATH = EVALUATION_DIR / "k_boundary_formula_survey.md"
DEFAULT_OFFSETS = tuple(range(-3, 4))


class BoundaryCase(NamedTuple):
    spec_name: str
    property_name: str
    expect_violated: bool
    note: str
    concrete_family: Optional[str] = None


CASES = [
    BoundaryCase(
        spec_name="fsm2petrinet_concrete.dslt",
        property_name="SMHasTwoNets_ShouldFail",
        expect_violated=True,
        note="Negative diagnostic expected to require the theorem-facing per-class cutoff to witness duplication.",
        concrete_family="fsm_sm",
    ),
    BoundaryCase(
        spec_name="fsm2petrinet_concrete.dslt",
        property_name="StateHasTwoPlaces_ShouldFail",
        expect_violated=True,
        note="Second FSM multiplicity diagnostic to confirm the same family is not a one-off.",
    ),
    BoundaryCase(
        spec_name="class2relational_concrete.dslt",
        property_name="Diag_AbstractClassNoDirectTable_ShouldFail",
        expect_violated=True,
        note="Negative diagnostic for abstract classes; exercises a larger K, `d=2`, and `a=4`.",
    ),
    BoundaryCase(
        spec_name="class2relational_concrete.dslt",
        property_name="Diag_DataTypeBecomesTable_ShouldFail",
        expect_violated=True,
        note="Small coarse-bound negative diagnostic from the same canonical benchmark.",
    ),
    BoundaryCase(
        spec_name="bpmn2petri_concrete.dslt",
        property_name="StartEventHasTwoPlaces",
        expect_violated=True,
        note="Canonical negative BPMN property with a very small theorem-facing cutoff.",
        concrete_family="bpmn_start",
    ),
    BoundaryCase(
        spec_name="persons_concrete.dslt",
        property_name="SonBecomesMan",
        expect_violated=False,
        note="Positive property used as a monotonicity sanity check.",
        concrete_family="persons_son",
    ),
    BoundaryCase(
        spec_name="attributes_concrete.dslt",
        property_name="HighPriorityItemRecorded",
        expect_violated=False,
        note="Small positive control where the tight bound is the unique minimum.",
    ),
    BoundaryCase(
        spec_name="ecore2jsonschema_concrete.dslt",
        property_name="AttributeHasRef_ShouldFail",
        expect_violated=True,
        note="Higher-arity case (`a=3`) drawn from an existing non-synthetic example.",
    ),
    BoundaryCase(
        spec_name="deep_dependency_boundary_concrete.dslt",
        property_name="DeepLeafMapsToTwoTD_ShouldFail",
        expect_violated=True,
        note="Synthetic deep-dependency negative control with the same `d=3` chain.",
        concrete_family="deep_chain_negative",
    ),
    BoundaryCase(
        spec_name="target_tight_boundary_concrete.dslt",
        property_name="SourceHasTwoTB_ShouldFail",
        expect_violated=True,
        note="Synthetic target-tight case where lowering the auxiliary target class `TA` by one should eliminate the counterexample.",
        concrete_family="target_tight",
    ),
    BoundaryCase(
        spec_name="target_tight_boundary_concrete.dslt",
        property_name="SourceHasTwoTD_ShouldFail",
        expect_violated=True,
        note="Synthetic target-tight case where lowering the auxiliary target class `TC` by one should eliminate the counterexample.",
        concrete_family="target_tight",
    ),
    BoundaryCase(
        spec_name="target_tight_boundary_concrete.dslt",
        property_name="SourceHasTwoTF_ShouldFail",
        expect_violated=True,
        note="Synthetic target-tight case where lowering the auxiliary target class `TE` by one should eliminate the counterexample.",
        concrete_family="target_tight",
    ),
]


@contextmanager
def patched_per_class_bounds(
    uniform_offset: int = 0,
    source_deltas: Optional[dict[str, int]] = None,
    target_deltas: Optional[dict[str, int]] = None,
):
    original_compute = smt_direct._compute_per_class_type_bounds
    original_source_bound_for = smt_direct.SMTModelEncoder.source_bound_for
    original_target_bound_for = smt_direct.SMTModelEncoder.target_bound_for
    source_deltas = source_deltas or {}
    target_deltas = target_deltas or {}

    def patched_compute(*args, **kwargs):
        src_bounds, tgt_bounds = original_compute(*args, **kwargs)
        patched_src = {
            k: max(0, v + uniform_offset + source_deltas.get(k, 0))
            for k, v in src_bounds.items()
        }
        patched_tgt = {
            k: max(0, v + uniform_offset + target_deltas.get(k, 0))
            for k, v in tgt_bounds.items()
        }
        return patched_src, patched_tgt

    def patched_source_bound_for(self, cls_name: str) -> int:
        return max(0, self.source_class_bounds.get(cls_name, self.bound))

    def patched_target_bound_for(self, cls_name: str) -> int:
        return max(0, self.target_class_bounds.get(cls_name, self.bound))

    smt_direct._compute_per_class_type_bounds = patched_compute
    smt_direct.SMTModelEncoder.source_bound_for = patched_source_bound_for
    smt_direct.SMTModelEncoder.target_bound_for = patched_target_bound_for
    try:
        yield
    finally:
        smt_direct._compute_per_class_type_bounds = original_compute
        smt_direct.SMTModelEncoder.source_bound_for = original_source_bound_for
        smt_direct.SMTModelEncoder.target_bound_for = original_target_bound_for


def _verification_config(bound: int, timeout_ms: int) -> SMTDirectConfig:
    return SMTDirectConfig(
        bound=max(bound, 1),
        use_cutoff=False,
        timeout_ms=timeout_ms,
        use_property_slicing=False,
        use_metamodel_slicing=False,
        prune_unconsumed_trace_producers=False,
        reduce_unused_string_domains=False,
        lazy_target_world_refinement=True,
        use_per_class_type_bounds=True,
        per_class_bounds_analysis="fixed_point",
        per_class_bound_mode="strict_theorem",
        use_incremental_property_check=False,
        auto_incremental_fallback=False,
        relax_source_containment_for_proving=False,
        strict_recheck_on_relaxed_sat=False,
    )


def _format_bounds(bounds: dict[str, int]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(bounds.items()))


def _formula_values(details) -> dict[str, int]:
    return {
        "coarse": details.bound_coarse,
        "sharp": details.bound_sharp,
        "sharp2": details.bound_sharp2,
        "tight": details.bound_tight,
    }


def _dominant_formulas(details) -> list[str]:
    values = _formula_values(details)
    minimum = min(values.values())
    return [name for name, value in values.items() if value == minimum]


def _load_case(case: BoundaryCase, dependency_mode: str) -> dict:
    spec_path = EXAMPLES_DIR / case.spec_name
    spec = parse_dsltrans_file(spec_path)
    prop = next((p for p in spec.properties if p.name == case.property_name), None)
    if prop is None:
        raise ValueError(f"Property {case.property_name} not found in {case.spec_name}")
    transformation = spec.transformations[0]
    details = compute_cutoff_bound_detailed(
        transformation,
        prop,
        use_reduced_k=True,
        dependency_mode=dependency_mode,
        ignore_containment_for_arity=False,
        use_path_aware_depth=False,
    )
    relevant_rule_ids = set(details.relevant_rule_ids) or {r.id for r in transformation.all_rules}
    src_bounds, tgt_bounds = compute_per_class_slot_bounds_fixed_point(
        transformation=transformation,
        property=prop,
        relevant_rule_ids=relevant_rule_ids,
        global_bound=details.bound,
    )
    source_class_names = {c.name for c in transformation.source_metamodel.classes}
    target_class_names = {c.name for c in transformation.target_metamodel.classes}
    relevant_src_classes = sorted(
        cls_name for cls_name in details.relevant_class_names if cls_name in source_class_names
    )
    relevant_tgt_classes = sorted(
        cls_name for cls_name in details.relevant_class_names if cls_name in target_class_names
    )
    return {
        "spec": spec,
        "prop": prop,
        "transformation": transformation,
        "details": details,
        "src_bounds": src_bounds,
        "tgt_bounds": tgt_bounds,
        "relevant_src_classes": relevant_src_classes,
        "relevant_tgt_classes": relevant_tgt_classes,
    }


def _verify_property(spec, prop, bound: int, timeout_ms: int) -> dict:
    verifier = SMTDirectVerifier(spec, _verification_config(bound, timeout_ms))
    start = time.perf_counter()
    result = verifier.verify_property(prop)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return {
        "status": result.result.name,
        "elapsed_ms": round(elapsed_ms, 1),
        "message": getattr(result, "message", ""),
    }


def _legacy_expectation(expect_violated: bool, runs: list[dict]) -> Optional[bool]:
    statuses = {run["offset"]: run["status"] for run in runs}
    if not {-1, 0, 1}.issubset(statuses):
        return None
    if expect_violated:
        return statuses[-1] != "VIOLATED" and statuses[0] == "VIOLATED" and statuses[1] == "VIOLATED"
    return statuses[-1] == "HOLDS" and statuses[0] == "HOLDS" and statuses[1] == "HOLDS"


def _run_uniform_sweep(spec, prop, bound: int, timeout_ms: int, offsets: tuple[int, ...]) -> list[dict]:
    runs: list[dict] = []
    for offset in offsets:
        with patched_per_class_bounds(uniform_offset=offset):
            outcome = _verify_property(spec, prop, bound, timeout_ms)
        runs.append({"offset": offset, **outcome})
    return runs


def _run_selective_perturbations(
    spec,
    prop,
    bound: int,
    timeout_ms: int,
    src_bounds: dict[str, int],
    tgt_bounds: dict[str, int],
    base_status: str,
    src_classes: list[str] | None = None,
    tgt_classes: list[str] | None = None,
) -> dict[str, list[dict]]:
    source_runs: list[dict] = []
    target_runs: list[dict] = []
    src_iter = sorted(src_classes) if src_classes is not None else sorted(src_bounds)
    tgt_iter = sorted(tgt_classes) if tgt_classes is not None else sorted(tgt_bounds)
    for cls_name in src_iter:
        with patched_per_class_bounds(source_deltas={cls_name: -1}):
            outcome = _verify_property(spec, prop, bound, timeout_ms)
        source_runs.append(
            {
                "class_name": cls_name,
                "base_bound": src_bounds[cls_name],
                "new_bound": max(0, src_bounds[cls_name] - 1),
                "changed": outcome["status"] != base_status,
                **outcome,
            }
        )
    for cls_name in tgt_iter:
        with patched_per_class_bounds(target_deltas={cls_name: -1}):
            outcome = _verify_property(spec, prop, bound, timeout_ms)
        target_runs.append(
            {
                "class_name": cls_name,
                "base_bound": tgt_bounds[cls_name],
                "new_bound": max(0, tgt_bounds[cls_name] - 1),
                "changed": outcome["status"] != base_status,
                **outcome,
            }
        )
    return {"source": source_runs, "target": target_runs}


def _write_xmi(name: str, lines: list[str]) -> Path:
    path = TMP_DIR / name
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _generate_fsm_model(sm_count: int, states_per_sm: int = 1) -> Path:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
    ]
    transition_id = 0
    state_id = 0
    for sm_idx in range(sm_count):
        sm_id = f"sm{sm_idx}"
        lines.append(f'  <objects xmi:id="{sm_id}" xsi:type="FSM:StateMachine" name="{sm_id}"/>')
        state_ids: list[str] = []
        for _ in range(max(states_per_sm, 1)):
            s_id = f"s{state_id}"
            state_id += 1
            state_ids.append(s_id)
            lines.append(f'  <objects xmi:id="{s_id}" xsi:type="FSM:State" name="{s_id}"/>')
            lines.append(f'  <links xsi:type="FSM:states" source="{sm_id}" target="{s_id}"/>')
        if len(state_ids) >= 2:
            t_id = f"t{transition_id}"
            transition_id += 1
            lines.append(f'  <objects xmi:id="{t_id}" xsi:type="FSM:Transition" name="{t_id}"/>')
            lines.append(f'  <links xsi:type="FSM:transitions" source="{sm_id}" target="{t_id}"/>')
            lines.append(f'  <links xsi:type="FSM:src" source="{t_id}" target="{state_ids[0]}"/>')
            lines.append(f'  <links xsi:type="FSM:dst" source="{t_id}" target="{state_ids[1]}"/>')
    lines.append("</model>")
    return _write_xmi(f"fsm_sm_{sm_count}_{states_per_sm}.xmi", lines)


def _generate_bpmn_start_model(start_count: int) -> Path:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        '  <objects xmi:id="defs1" xsi:type="BPMN:Definitions"/>',
        '  <objects xmi:id="proc1" xsi:type="BPMN:Process"/>',
        '  <links xsi:type="BPMN:processes" source="defs1" target="proc1"/>',
    ]
    for idx in range(start_count):
        sid = f"start{idx}"
        lines.append(f'  <objects xmi:id="{sid}" xsi:type="BPMN:StartEvent"/>')
        lines.append(f'  <links xsi:type="BPMN:flowNodes" source="proc1" target="{sid}"/>')
    lines.append("</model>")
    return _write_xmi(f"bpmn_start_{start_count}.xmi", lines)


def _generate_persons_son_model(son_count: int) -> Path:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        '  <objects xmi:id="model1" xsi:type="Household:Model"/>',
        '  <objects xmi:id="hs1" xsi:type="Household:Households"/>',
        '  <links xsi:type="Household:root" source="model1" target="hs1"/>',
        '  <objects xmi:id="fam1" xsi:type="Household:Family"/>',
        '  <links xsi:type="Household:have" source="hs1" target="fam1"/>',
    ]
    for idx in range(son_count):
        mid = f"son{idx}"
        lines.append(
            f'  <objects xmi:id="{mid}" xsi:type="Household:Member" isActive="true" roleTag="Son" role="Son"/>'
        )
        lines.append(f'  <links xsi:type="Household:members" source="hs1" target="{mid}"/>')
        lines.append(f'  <links xsi:type="Household:son" source="fam1" target="{mid}"/>')
    lines.append("</model>")
    return _write_xmi(f"persons_son_{son_count}.xmi", lines)


def _generate_deep_chain_model(chain_count: int) -> Path:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        '  <objects xmi:id="root1" xsi:type="DeepSrc:Root"/>',
    ]
    for idx in range(chain_count):
        a_id = f"a{idx}"
        b_id = f"b{idx}"
        c_id = f"c{idx}"
        d_id = f"d{idx}"
        lines.append(f'  <objects xmi:id="{a_id}" xsi:type="DeepSrc:A"/>')
        lines.append(f'  <objects xmi:id="{b_id}" xsi:type="DeepSrc:B"/>')
        lines.append(f'  <objects xmi:id="{c_id}" xsi:type="DeepSrc:C"/>')
        lines.append(f'  <objects xmi:id="{d_id}" xsi:type="DeepSrc:D"/>')
        lines.append(f'  <links xsi:type="DeepSrc:rootA" source="root1" target="{a_id}"/>')
        lines.append(f'  <links xsi:type="DeepSrc:aB" source="{a_id}" target="{b_id}"/>')
        lines.append(f'  <links xsi:type="DeepSrc:bC" source="{b_id}" target="{c_id}"/>')
        lines.append(f'  <links xsi:type="DeepSrc:cD" source="{c_id}" target="{d_id}"/>')
    lines.append("</model>")
    return _write_xmi(f"deep_chain_{chain_count}.xmi", lines)


def _generate_target_tight_model(source_count: int) -> Path:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        '  <objects xmi:id="root1" xsi:type="TightSrc:Root"/>',
    ]
    for idx in range(source_count):
        sid = f"s{idx}"
        lines.append(f'  <objects xmi:id="{sid}" xsi:type="TightSrc:S"/>')
        lines.append(f'  <links xsi:type="TightSrc:rootS" source="root1" target="{sid}"/>')
    lines.append("</model>")
    return _write_xmi(f"target_tight_{source_count}.xmi", lines)


def _run_concrete(spec_path: Path, input_path: Path) -> dict[str, str] | None:
    out_xmi = TMP_DIR / f"{spec_path.stem}_{input_path.stem}_out.xmi"
    out_json = TMP_DIR / f"{spec_path.stem}_{input_path.stem}_props.json"
    cmd = [
        sys.executable,
        "-m",
        "dsltrans.run",
        "--spec",
        str(spec_path),
        "--in",
        str(input_path),
        "--out",
        str(out_xmi),
        "--check-concrete-properties",
        "--property-report",
        str(out_json),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env=env)
    if res.returncode != 0 or not out_json.exists():
        return None
    data = json.loads(out_json.read_text(encoding="utf-8"))
    return {row["name"]: str(row["status"]).upper() for row in data}


def _concrete_inputs_for_case(case: BoundaryCase) -> list[tuple[str, Path]]:
    family = case.concrete_family
    if family == "fsm_sm":
        return [
            ("base-1", _generate_fsm_model(0, states_per_sm=2)),
            ("base", _generate_fsm_model(1, states_per_sm=2)),
            ("base+1", _generate_fsm_model(2, states_per_sm=2)),
        ]
    if family == "fsm_state":
        return [
            ("base-1", _generate_fsm_model(1, states_per_sm=1)),
            ("base", _generate_fsm_model(1, states_per_sm=2)),
            ("base+1", _generate_fsm_model(1, states_per_sm=3)),
        ]
    if family == "bpmn_start":
        return [
            ("base-1", _generate_bpmn_start_model(0)),
            ("base", _generate_bpmn_start_model(1)),
            ("base+1", _generate_bpmn_start_model(2)),
        ]
    if family == "persons_son":
        return [
            ("base-1", _generate_persons_son_model(0)),
            ("base", _generate_persons_son_model(1)),
            ("base+1", _generate_persons_son_model(2)),
        ]
    if family == "deep_chain_positive":
        return [
            ("base-1", _generate_deep_chain_model(0)),
            ("base", _generate_deep_chain_model(1)),
            ("base+1", _generate_deep_chain_model(2)),
        ]
    if family == "deep_chain_negative":
        return [
            ("base-1", _generate_deep_chain_model(0)),
            ("base", _generate_deep_chain_model(1)),
            ("base+1", _generate_deep_chain_model(2)),
        ]
    if family == "target_tight":
        return [
            ("base-1", _generate_target_tight_model(0)),
            ("base", _generate_target_tight_model(1)),
            ("base+1", _generate_target_tight_model(2)),
        ]
    return []


def _concrete_expectation(case: BoundaryCase, label: str, status: str) -> bool:
    if case.expect_violated:
        if label == "base-1":
            return status != "VIOLATED"
        return status == "VIOLATED"
    if label == "base-1":
        return status in {"HOLDS", "PRECONDITION_NEVER_MATCHED"}
    return status == "HOLDS"


def _run_concrete_validation(case: BoundaryCase) -> list[dict]:
    spec_path = EXAMPLES_DIR / case.spec_name
    runs: list[dict] = []
    for label, input_path in _concrete_inputs_for_case(case):
        props = _run_concrete(spec_path, input_path)
        status = props.get(case.property_name, "ERROR") if props is not None else "ERROR"
        runs.append(
            {
                "label": label,
                "input": input_path.name,
                "status": status,
                "matches_expectation": _concrete_expectation(case, label, status),
            }
        )
    return runs


def run_boundary_case(
    case: BoundaryCase,
    timeout_ms: int,
    dependency_mode: str,
    offsets: tuple[int, ...] = DEFAULT_OFFSETS,
) -> dict:
    loaded = _load_case(case, dependency_mode)
    spec = loaded["spec"]
    prop = loaded["prop"]
    details = loaded["details"]
    src_bounds = loaded["src_bounds"]
    tgt_bounds = loaded["tgt_bounds"]

    uniform_runs = _run_uniform_sweep(spec, prop, details.bound, timeout_ms, offsets)
    base_run = next(run for run in uniform_runs if run["offset"] == 0)
    selective_runs = _run_selective_perturbations(
        spec,
        prop,
        details.bound,
        timeout_ms,
        src_bounds,
        tgt_bounds,
        base_run["status"],
        src_classes=loaded["relevant_src_classes"],
        tgt_classes=loaded["relevant_tgt_classes"],
    )
    concrete_runs = _run_concrete_validation(case) if case.concrete_family else []

    dominant_formulas = _dominant_formulas(details)
    return {
        "case": case,
        "details": details,
        "src_bounds": src_bounds,
        "tgt_bounds": tgt_bounds,
        "uniform_runs": uniform_runs,
        "runs": uniform_runs,
        "base_status": base_run["status"],
        "dominant_formulas": dominant_formulas,
        "formula_signature": "/".join(dominant_formulas),
        "matches_expectation": _legacy_expectation(case.expect_violated, uniform_runs),
        "selective_runs": selective_runs,
        "concrete_runs": concrete_runs,
    }


def compute_formula_survey(example_paths: list[Path], dependency_mode: str) -> dict:
    rows: list[dict] = []
    signature_counts: Counter[str] = Counter()
    relation_failures: list[dict] = []
    for path in sorted(example_paths):
        try:
            spec = parse_dsltrans_file(path)
        except Exception:
            continue
        if not spec.transformations:
            continue
        transformation = spec.transformations[0]
        for prop in spec.properties:
            try:
                details = compute_cutoff_bound_detailed(
                    transformation,
                    prop,
                    use_reduced_k=True,
                    dependency_mode=dependency_mode,
                )
            except Exception:
                continue
            dominant = _dominant_formulas(details)
            signature = "/".join(dominant)
            signature_counts[signature] += 1
            if not (details.bound_tight <= details.bound_sharp and details.bound_tight <= details.bound_sharp2):
                relation_failures.append(
                    {
                        "spec": path.name,
                        "property": prop.name,
                        "tight": details.bound_tight,
                        "sharp": details.bound_sharp,
                        "sharp2": details.bound_sharp2,
                    }
                )
            rows.append(
                {
                    "spec": path.name,
                    "property": prop.name,
                    "signature": signature,
                    "bound": details.bound,
                    "d": details.d,
                    "a": details.a,
                    "c": details.c,
                    "m": details.m,
                    "p": details.p,
                    "r": details.r,
                    "bound_coarse": details.bound_coarse,
                    "bound_sharp": details.bound_sharp,
                    "bound_sharp2": details.bound_sharp2,
                    "bound_tight": details.bound_tight,
                }
            )
    return {
        "rows": rows,
        "signature_counts": signature_counts,
        "relation_failures": relation_failures,
    }


def write_formula_survey(survey: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = survey["rows"]
    signature_counts = survey["signature_counts"]
    relation_failures = survey["relation_failures"]
    top_depth = sorted(rows, key=lambda row: (-row["d"], row["bound"], row["spec"], row["property"]))[:10]
    top_arity = sorted(rows, key=lambda row: (-row["a"], row["bound"], row["spec"], row["property"]))[:10]
    representative = []
    seen = set()
    for row in rows:
        sig = row["signature"]
        if sig not in seen:
            representative.append(row)
            seen.add(sig)
    lines = [
        "# K-Boundary Formula Survey",
        "",
        "Generated by `dsltrans-prover/scripts/run_k_boundary_testing.py`.",
        "",
        f"- Total evaluated properties: `{len(rows)}`",
        f"- Dominance signatures observed: `{len(signature_counts)}`",
        f"- `bound_tight <= bound_sharp` failures: `{sum(1 for row in rows if row['bound_tight'] > row['bound_sharp'])}`",
        f"- `bound_tight <= bound_sharp2` failures: `{len(relation_failures)}`",
        "",
        "## Dominance Signatures",
        "",
        "| Signature | Count |",
        "| --- | --- |",
    ]
    for signature, count in sorted(signature_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {signature} | {count} |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- No case should be uniquely `sharp`- or `sharp2`-dominant under the current reduced-K selection if `bound_tight` is also included.",
            "- The survey checks this empirically by verifying `bound_tight <= bound_sharp` and `bound_tight <= bound_sharp2` for every scanned property.",
            "",
            "## Representative Examples",
            "",
            "| Signature | Spec | Property | K | d | a |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in representative[:20]:
        lines.append(
            f"| {row['signature']} | {row['spec']} | {row['property']} | {row['bound']} | {row['d']} | {row['a']} |"
        )
    lines.extend(
        [
            "",
            "## Highest Dependency Depth",
            "",
            "| Spec | Property | K | d | a | Signature |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in top_depth:
        lines.append(
            f"| {row['spec']} | {row['property']} | {row['bound']} | {row['d']} | {row['a']} | {row['signature']} |"
        )
    lines.extend(
        [
            "",
            "## Highest Association Arity",
            "",
            "| Spec | Property | K | d | a | Signature |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in top_arity:
        lines.append(
            f"| {row['spec']} | {row['property']} | {row['bound']} | {row['d']} | {row['a']} | {row['signature']} |"
        )
    if relation_failures:
        lines.extend(
            [
                "",
                "## Tight-vs-Sharp2 Relation Failures",
                "",
                "| Spec | Property | tight | sharp | sharp2 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in relation_failures:
            lines.append(
                f"| {row['spec']} | {row['property']} | {row['tight']} | {row['sharp']} | {row['sharp2']} |"
            )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_results(
    results: list[dict],
    out_path: Path,
    dependency_mode: str,
    timeout_ms: int,
    offsets: tuple[int, ...] = DEFAULT_OFFSETS,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Expanded K-Boundary Testing Results",
        "",
        "Generated by `dsltrans-prover/scripts/run_k_boundary_testing.py`.",
        "This expanded evaluation extends the original `K-1/K/K+1` experiment with a wider symbolic sweep,",
        "per-class selective perturbation, formula-breakdown reporting, and representative concrete validation.",
        "",
        f"- Dependency mode: `{dependency_mode}`",
        f"- Timeout per symbolic run: `{timeout_ms}` ms",
        f"- Uniform sweep offsets: `{', '.join(str(offset) for offset in offsets)}`",
        "- Verification profile: no property slicing, no metamodel slicing, no containment relaxation, no trace-producer pruning, per-class fixed-point bounds enabled.",
        "",
        "## Summary",
        "",
        "| Spec | Property | Expected | Base K | d | a | Dominant formula(s) | Legacy K-1/K/K+1 expectation? | Source bottlenecks | Target bottlenecks | Concrete validation |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in results:
        case = item["case"]
        selective_runs = item.get("selective_runs", {"source": [], "target": []})
        source_changed = sum(1 for run in selective_runs.get("source", []) if run.get("changed"))
        target_changed = sum(1 for run in selective_runs.get("target", []) if run.get("changed"))
        concrete_runs = item.get("concrete_runs", [])
        concrete_ok = (
            f"{sum(1 for run in concrete_runs if run.get('matches_expectation'))}/{len(concrete_runs)}"
            if concrete_runs
            else "-"
        )
        lines.append(
            f"| {case.spec_name} | {case.property_name} | {'VIOLATED at base' if case.expect_violated else 'HOLDS at base'} | "
            f"{item['details'].bound} | {item['details'].d} | {item['details'].a} | {item.get('formula_signature', '-')} | "
            f"{'Yes' if item.get('matches_expectation') else ('No' if item.get('matches_expectation') is False else 'N/A')} | "
            f"{source_changed} | {target_changed} | {concrete_ok} |"
        )
    for item in results:
        case = item["case"]
        details = item["details"]
        runs = item.get("uniform_runs", item.get("runs", []))
        bound_coarse = getattr(details, "bound_coarse", "-")
        bound_sharp = getattr(details, "bound_sharp", "-")
        bound_sharp2 = getattr(details, "bound_sharp2", "-")
        bound_tight = getattr(details, "bound_tight", "-")
        lines.extend(
            [
                "",
                f"## {case.property_name}",
                "",
                f"- Spec: `{case.spec_name}`",
                f"- Expected base behavior: {'VIOLATED' if case.expect_violated else 'HOLDS'}",
                f"- Note: {case.note}",
                f"- Reduced cutoff detail: `K={details.bound}`, `c={details.c}`, `m={details.m}`, `p={details.p}`, `d={details.d}`, `a={details.a}`, `r={details.r}`",
                f"- Formula values: `coarse={bound_coarse}`, `sharp={bound_sharp}`, `sharp2={bound_sharp2}`, `tight={bound_tight}`",
                f"- Dominant formula signature: `{item.get('formula_signature', '-')}`",
                f"- Base source bounds: `{_format_bounds(item['src_bounds'])}`",
                f"- Base target bounds: `{_format_bounds(item['tgt_bounds'])}`",
                "",
                "### Uniform Sweep",
                "",
                "| Offset | Result | Time (ms) | Message |",
                "| --- | --- | --- | --- |",
            ]
        )
        for run in runs:
            lines.append(
                f"| K{run['offset']:+d} | {run['status']} | {run['elapsed_ms']} | {run['message'] or '-'} |"
            )
        selective_runs = item.get("selective_runs", {"source": [], "target": []})
        lines.extend(
            [
                "",
                "### Source Selective `-1` Perturbation",
                "",
                "| Class | Base | New | Result | Changed base? |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for run in selective_runs.get("source", []):
            lines.append(
                f"| {run['class_name']} | {run['base_bound']} | {run['new_bound']} | {run['status']} | {'Yes' if run['changed'] else 'No'} |"
            )
        lines.extend(
            [
                "",
                "### Target Selective `-1` Perturbation",
                "",
                "| Class | Base | New | Result | Changed base? |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for run in selective_runs.get("target", []):
            lines.append(
                f"| {run['class_name']} | {run['base_bound']} | {run['new_bound']} | {run['status']} | {'Yes' if run['changed'] else 'No'} |"
            )
        concrete_runs = item.get("concrete_runs", [])
        if concrete_runs:
            lines.extend(
                [
                    "",
                    "### Concrete Witness Validation",
                    "",
                    "| Support level | Input | Result | Matches expectation? |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for run in concrete_runs:
                lines.append(
                    f"| {run['label']} | {run['input']} | {run['status']} | {'Yes' if run['matches_expectation'] else 'No'} |"
                )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=300_000)
    parser.add_argument("--dependency-mode", default="trace_attr_aware")
    parser.add_argument("--out", type=str, default=None, help="Expanded evaluation markdown path.")
    parser.add_argument("--formula-out", type=str, default=None, help="Formula survey markdown path.")
    parser.add_argument("--offsets", nargs="*", type=int, default=list(DEFAULT_OFFSETS), help="Uniform symbolic offset sweep.")
    parser.add_argument("--specs", nargs="*", default=None, help="Restrict to these spec names.")
    args = parser.parse_args()

    offsets = tuple(args.offsets)
    selected_cases = CASES
    if args.specs:
        allowed = set(args.specs)
        selected_cases = [case for case in CASES if case.spec_name in allowed]

    results = []
    for case in selected_cases:
        print(f"--- Testing Property: {case.property_name} ({case.spec_name}) ---", flush=True)
        result = run_boundary_case(
            case,
            timeout_ms=args.timeout,
            dependency_mode=args.dependency_mode,
            offsets=offsets,
        )
        print(
            f"  Base K: {result['details'].bound} | d={result['details'].d} | a={result['details'].a} | dominant={result['formula_signature']}",
            flush=True,
        )
        for run in result["uniform_runs"]:
            print(f"  K{run['offset']:+d}: {run['status']} ({run['elapsed_ms']:.1f} ms)", flush=True)
        results.append(result)

    out_path = Path(args.out) if args.out else OUT_PATH
    write_results(
        results,
        out_path=out_path,
        dependency_mode=args.dependency_mode,
        timeout_ms=args.timeout,
        offsets=offsets,
    )
    print(f"Wrote {out_path}", flush=True)

    formula_survey = compute_formula_survey(list(EXAMPLES_DIR.glob("*.dslt")), args.dependency_mode)
    formula_out = Path(args.formula_out) if args.formula_out else FORMULA_SURVEY_PATH
    write_formula_survey(formula_survey, formula_out)
    print(f"Wrote {formula_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
