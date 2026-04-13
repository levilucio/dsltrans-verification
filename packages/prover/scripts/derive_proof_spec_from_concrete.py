from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dsltrans.abstraction import make_default_abstraction_policy, synthesize_abstract_spec
from dsltrans.parser import parse_dsltrans_file
from dsltrans.spec_writer import render_spec


def _default_outputs(spec_path: Path) -> tuple[Path, Path, Path]:
    out_dir = spec_path.parent / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = spec_path.stem.replace("_concrete", "")
    return (
        out_dir / f"{stem}_proof_generated.dslt",
        out_dir / f"{stem}_proof_abstraction_report.json",
        out_dir / f"{stem}_proof_abstraction_report.md",
    )


def _render_markdown_report(result, concrete_spec_path: Path, abstract_spec_path: Path) -> str:
    lines: list[str] = []
    lines.append("# Concrete-to-Proof Abstraction Report")
    lines.append("")
    lines.append(f"- Concrete spec: `{concrete_spec_path}`")
    lines.append(f"- Generated proof spec: `{abstract_spec_path}`")
    lines.append("")
    lines.append("## Mappings")
    lines.append("")
    lines.append("| Concrete | Proof |")
    lines.append("|---|---|")
    for src, tgt in result.metamodel_mapping.items():
        lines.append(f"| metamodel `{src}` | `{tgt}` |")
    for src, tgt in result.transformation_mapping.items():
        lines.append(f"| transformation `{src}` | `{tgt}` |")
    lines.append("")
    lines.append("## Attribute Decisions")
    lines.append("")
    lines.append("| Metamodel | Class | Attribute | Concrete Type | Abstract Type | Decision | Reason |")
    lines.append("|---|---|---|---|---|---|---|")
    for d in result.attribute_decisions:
        reason = d.reason.replace("|", "\\|")
        lines.append(
            f"| `{d.metamodel}` | `{d.class_name}` | `{d.attribute_name}` | `{d.concrete_type}` | "
            f"`{d.abstract_type}` | `{d.decision}` | {reason} |"
        )
    lines.append("")
    lines.append("## Property Projection")
    lines.append("")
    lines.append("| Property | Status | Reason |")
    lines.append("|---|---|---|")
    for d in result.property_decisions:
        reason = d.reason.replace("|", "\\|")
        lines.append(f"| `{d.property_name}` | `{d.status}` | {reason} |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- The concrete spec remains the source of truth.")
    lines.append("- The generated proof spec preserves the same structure and attribute surface.")
    lines.append("- Infinite domains are replaced by finite proof domains; unused finite string domains may be reduced further during SMT encoding.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate finite proof DSLT spec from a concrete source-of-truth spec.")
    parser.add_argument("--spec", required=True, help="Concrete DSLT specification path")
    parser.add_argument("--out-spec", default=None, help="Path to generated proof spec")
    parser.add_argument("--out-report-json", default=None, help="Path to JSON abstraction report")
    parser.add_argument("--out-report-md", default=None, help="Path to Markdown abstraction report")
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    concrete_spec = parse_dsltrans_file(spec_path)
    policy = make_default_abstraction_policy(concrete_spec)

    result = synthesize_abstract_spec(concrete_spec, policy)

    default_out_spec, default_out_json, default_out_md = _default_outputs(spec_path)
    out_spec = Path(args.out_spec).resolve() if args.out_spec else default_out_spec
    out_json = Path(args.out_report_json).resolve() if args.out_report_json else default_out_json
    out_md = Path(args.out_report_md).resolve() if args.out_report_md else default_out_md

    out_spec.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    out_spec.write_text(render_spec(result.abstract_spec), encoding="utf-8")
    out_json.write_text(json.dumps(result.to_json_dict(), indent=2), encoding="utf-8")
    out_md.write_text(_render_markdown_report(result, spec_path, out_spec), encoding="utf-8")

    print(f"Wrote generated proof spec: {out_spec}")
    print(f"Wrote abstraction report JSON: {out_json}")
    print(f"Wrote abstraction report Markdown: {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
