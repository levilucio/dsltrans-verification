from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from .concrete_property_checker import check_properties_concrete
from .ecore_io import check_metamodel_consistency, load_ecore_model
from .parser import parse_dsltrans_file
from .runtime_engine import execute_transformation
from .xmi_io import load_xmi_model, save_xmi_model


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Execute DSLTrans fragment transformations on XMI models.")
    p.add_argument("--spec", required=True, help="Path to DSLTrans .dslt specification")
    p.add_argument("--in", dest="input_model", required=True, help="Path to source XMI model")
    p.add_argument("--out", required=True, help="Path to output XMI model")
    p.add_argument(
        "--transformation",
        default=None,
        help="Transformation name from spec (default: first transformation)",
    )
    p.add_argument(
        "--source-ecore",
        default=None,
        help="Optional source Ecore for DSLT/Ecore consistency check",
    )
    p.add_argument(
        "--target-ecore",
        default=None,
        help="Optional target Ecore for DSLT/Ecore consistency check",
    )
    p.add_argument(
        "--artifact-dir",
        default=None,
        help="Optional directory for execution artifacts (Option B layout)",
    )
    p.add_argument(
        "--check-concrete-properties",
        action="store_true",
        help="Evaluate spec properties on this concrete execution (uses output traces)",
    )
    p.add_argument(
        "--property-report",
        default=None,
        help="Path for property results JSON (default: property_results.json in --artifact-dir or cwd)",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()
    spec = parse_dsltrans_file(Path(args.spec))
    if not spec.transformations:
        raise ValueError("No transformation found in specification")

    if args.transformation is None:
        trans = spec.transformations[0]
    else:
        by_name = {t.name: t for t in spec.transformations}
        if args.transformation not in by_name:
            raise ValueError(
                f"Unknown transformation {args.transformation!r}. "
                f"Available: {', '.join(sorted(by_name))}"
            )
        trans = by_name[args.transformation]

    if args.source_ecore:
        src_ecore = load_ecore_model(args.source_ecore)
        issues = check_metamodel_consistency(trans.source_metamodel, src_ecore)
        if issues:
            raise ValueError("Source metamodel mismatch:\n- " + "\n- ".join(issues))
    if args.target_ecore:
        tgt_ecore = load_ecore_model(args.target_ecore)
        issues = check_metamodel_consistency(trans.target_metamodel, tgt_ecore)
        if issues:
            raise ValueError("Target metamodel mismatch:\n- " + "\n- ".join(issues))

    source_model = load_xmi_model(args.input_model, trans.source_metamodel)
    target_model, stats = execute_transformation(trans, source_model)
    save_xmi_model(args.out, target_model, trans.target_metamodel.name)

    print(f"Transformation: {trans.name}")
    print(f"Layers: {trans.layer_count}, Rules: {trans.rule_count}")
    print(f"Created nodes={stats.created_nodes}, edges={stats.created_edges}, traces={stats.created_traces}")
    print(f"Wrote output model: {args.out}")

    property_payload: list[dict[str, object]] | None = None
    if args.check_concrete_properties:
        results = check_properties_concrete(
            transformation=trans,
            source_model=source_model,
            target_model=target_model,
            traces=target_model.traces,
            properties=spec.properties,
        )
        property_payload = []
        print("Concrete property results:")
        for res in results:
            row = {
                "id": res.property_id,
                "name": res.property_name,
                "status": res.status,
                "checked_pre_matches": res.checked_pre_matches,
                "violating_pre_match": res.violating_pre_match,
            }
            if res.message is not None:
                row["message"] = res.message
            property_payload.append(row)
            print(f"  - {res.property_name}: {res.status}")

    if args.artifact_dir:
        artifact_dir = Path(args.artifact_dir)
        input_dir = artifact_dir / "input"
        output_dir = artifact_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        input_copy = input_dir / Path(args.input_model).name
        output_copy = output_dir / Path(args.out).name
        shutil.copy2(args.input_model, input_copy)
        shutil.copy2(args.out, output_copy)

        summary = {
            "transformation": trans.name,
            "spec": str(args.spec),
            "input_model": str(Path("input") / input_copy.name),
            "output_model": str(Path("output") / output_copy.name),
            "stats": {
                "created_nodes": stats.created_nodes,
                "created_edges": stats.created_edges,
                "created_traces": stats.created_traces,
            },
        }
        (artifact_dir / "execution_result.json").write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote artifacts under: {artifact_dir}")

    if property_payload is not None:
        if args.property_report:
            property_result_path = Path(args.property_report)
        elif args.artifact_dir:
            property_result_path = Path(args.artifact_dir) / "property_results.json"
        else:
            property_result_path = Path("property_results.json")
        property_result_path.parent.mkdir(parents=True, exist_ok=True)
        property_result_path.write_text(
            json.dumps(property_payload, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote concrete property results: {property_result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
