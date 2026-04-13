#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent / "src"))

from dsltrans.cutoff import minimal_satisfying_layer_indices
from dsltrans.model import ApplyElement, ApplyLink, BackwardLink, MatchLink
from dsltrans.parser import parse_dsltrans_file
from run_cross_validation import (
    ROOT,
    DSLT_EXAMPLES,
    generate_bpmn_input,
    generate_component_input,
    generate_family_input,
    generate_fsm_input,
    generate_mindmap_input,
    generate_org_input,
    generate_statechart_input,
    generate_tree_input,
    generate_usecase_input,
    run_concrete,
)
from run_hybrid_cegar_stress import verify_property_hybrid

DOCS_DIR = ROOT / "docs" / "evaluation"
OUT_PATH = DOCS_DIR / "mutation_testing_results.md"
MUTATIONS_DIR = DSLT_EXAMPLES / "mutations"
TMP_RESULTS_DIR = ROOT / "cross_validation_tmp"
MAX_TYPE_SWAP_ALTERNATIVES = 2

TARGETS = [
    {
        "spec": DSLT_EXAMPLES / "persons_concrete.dslt",
        "input": lambda: DSLT_EXAMPLES / "persons_example" / "input" / "household_input.xmi",
    },
    {
        "spec": DSLT_EXAMPLES / "class2relational_concrete.dslt",
        "input": lambda: DSLT_EXAMPLES / "models" / "class2relational_minimal_input.xmi",
    },
    {
        "spec": DSLT_EXAMPLES / "uml2java_concrete_canonical.dslt",
        "input": lambda: DSLT_EXAMPLES / "models" / "uml2java_minimal_input.xmi",
    },
    {
        "spec": DSLT_EXAMPLES / "bpmn2petri_concrete.dslt",
        "input": generate_bpmn_input,
    },
    {
        "spec": DSLT_EXAMPLES / "fsm2petrinet_concrete.dslt",
        "input": generate_fsm_input,
    },
    {
        "spec": DSLT_EXAMPLES / "family2socialnetwork_concrete.dslt",
        "input": generate_family_input,
    },
    {
        "spec": DSLT_EXAMPLES / "tree2graph_concrete.dslt",
        "input": generate_tree_input,
    },
    {
        "spec": DSLT_EXAMPLES / "mindmap2graph_concrete.dslt",
        "input": generate_mindmap_input,
    },
    {
        "spec": DSLT_EXAMPLES / "statechart2flow_concrete.dslt",
        "input": generate_statechart_input,
    },
    {
        "spec": DSLT_EXAMPLES / "organization2accesscontrol_concrete.dslt",
        "input": generate_org_input,
    },
    {
        "spec": DSLT_EXAMPLES / "component2deployment_concrete.dslt",
        "input": generate_component_input,
    },
    {
        "spec": DSLT_EXAMPLES / "usecase2activity_concrete.dslt",
        "input": generate_usecase_input,
    },
]


class MutantCandidate(NamedTuple):
    family: str
    target_rule: str
    obligation: str
    description: str
    mutated_text: str


def _rule_block_bounds(lines: list[str], rule_name: str) -> tuple[int, int] | None:
    start = None
    depth = 0
    for idx, line in enumerate(lines):
        if start is None:
            if re.search(rf"\brule\s+{re.escape(rule_name)}\s*\{{", line):
                start = idx
                depth = line.count("{") - line.count("}")
                if depth <= 0:
                    return None
        else:
            depth += line.count("{") - line.count("}")
            if depth == 0:
                return start, idx
    return None


def _replace_unique_rule_line(
    text: str,
    rule_name: str,
    *,
    match: callable,
    replace: callable,
) -> str | None:
    lines = text.splitlines()
    bounds = _rule_block_bounds(lines, rule_name)
    if bounds is None:
        return None
    start, end = bounds
    matches = [idx for idx in range(start, end + 1) if match(lines[idx].strip())]
    if len(matches) != 1:
        return None
    idx = matches[0]
    old_line = lines[idx]
    indent = old_line[: len(old_line) - len(old_line.lstrip())]
    lines[idx] = indent + replace(old_line.strip())
    updated = "\n".join(lines)
    if text.endswith("\n"):
        updated += "\n"
    return updated


def _commented(line: str) -> str:
    return f"// MUTATED: {line}"


def _class_attr_names(metamodel, class_id) -> set[str]:
    current = metamodel.class_by_id.get(class_id)
    names: set[str] = set()
    while current is not None:
        names.update(attr.name for attr in current.attributes)
        current = metamodel.class_by_id.get(current.parent) if current.parent else None
    return names


def _apply_binding_names(elem: ApplyElement) -> set[str]:
    names = {binding.target.attribute for binding in elem.attribute_bindings}
    for assignment in elem.attribute_assignments:
        m = re.match(r"\s*([A-Za-z_]\w*)\s*[:=]", assignment)
        if m:
            names.add(m.group(1))
    return names


def _assoc_alternatives(metamodel, assoc_name: str) -> list[str]:
    assoc = metamodel.assoc_by_name.get(str(assoc_name))
    if assoc is None:
        return []
    return sorted(
        other.name
        for other in metamodel.associations
        if other.name != assoc.name
        and other.source_class == assoc.source_class
        and other.target_class == assoc.target_class
    )


def _compatible_class_alternatives(transformation, elem: ApplyElement, forbidden: set[str]) -> list[str]:
    assigned_attrs = _apply_binding_names(elem)
    compatible: list[str] = []
    for cls in transformation.target_metamodel.classes:
        if cls.is_abstract or str(cls.id) == str(elem.class_type):
            continue
        if assigned_attrs.issubset(_class_attr_names(transformation.target_metamodel, cls.id)):
            compatible.append(cls.name)
    compatible.sort(key=lambda name: (name in forbidden, name))
    return compatible


def _class_preserves_apply_link_typing(transformation, rule, elem: ApplyElement, new_class_name: str) -> bool:
    for link in rule.apply_links:
        src_elem = rule.apply_element_by_id[link.source]
        tgt_elem = rule.apply_element_by_id[link.target]
        actual_src = new_class_name if src_elem.id == elem.id else str(src_elem.class_type)
        actual_tgt = new_class_name if tgt_elem.id == elem.id else str(tgt_elem.class_type)
        assoc = transformation.target_metamodel.assoc_by_name.get(str(link.assoc_type))
        if assoc is None:
            return False
        if actual_src != str(assoc.source_class) or actual_tgt != str(assoc.target_class):
            return False
    return True


def _rules_in_layers(transformation, layer_indices: list[int]) -> list:
    chosen = set(layer_indices)
    return [rule for idx, layer in enumerate(transformation.layers) if idx in chosen for rule in layer.rules]


def _rule_priority(rule, pre_types: set[str], post_types: set[str]) -> tuple[int, int, int, int]:
    backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
    apply_types = {
        str(ae.class_type)
        for ae in rule.apply_elements
        if ae.id not in backward_apply_ids
    }
    match_types = {str(me.class_type) for me in rule.match_elements}
    return (
        len(apply_types & post_types),
        len(match_types & pre_types),
        -len(rule.apply_links),
        -len(rule.backward_links),
    )


def _pick_rule(rules: list, predicate, pre_types: set[str], post_types: set[str]):
    candidates = [rule for rule in rules if predicate(rule)]
    if not candidates:
        return None
    return max(candidates, key=lambda rule: _rule_priority(rule, pre_types, post_types))


def _line_for_apply_link(rule, link: ApplyLink) -> str:
    src = rule.apply_element_by_id[link.source].name
    tgt = rule.apply_element_by_id[link.target].name
    return f"{link.name} : {link.assoc_type} -- {src}.{tgt}"


def _line_for_match_link(rule, link: MatchLink) -> str:
    src = rule.match_element_by_id[link.source].name
    tgt = rule.match_element_by_id[link.target].name
    prefix = "indirect" if "INDIRECT" in str(link.kind) else "direct"
    return f"{prefix} {link.name} : {link.assoc_type} -- {src}.{tgt}"


def _line_for_backward_link(rule, link: BackwardLink) -> str:
    apply_name = rule.apply_element_by_id[link.apply_element].name
    match_name = rule.match_element_by_id[link.match_element].name
    return f"{apply_name} <--trace-- {match_name}"


def build_semantic_mutants(spec_text: str, spec, prop, max_mutants: int = 2) -> list[MutantCandidate]:
    transformation = spec.transformations[0]
    fragment_rules = _rules_in_layers(
        transformation,
        minimal_satisfying_layer_indices(transformation, prop),
    )
    precondition = prop.precondition
    pre_elem_by_id = {elem.id: elem for elem in (precondition.elements if precondition else ())}
    post_elem_by_id = {elem.id: elem for elem in prop.postcondition.elements}
    pre_types = {str(elem.class_type) for elem in pre_elem_by_id.values()}
    post_types = {str(elem.class_type) for elem in prop.postcondition.elements}
    forbidden_post_types = set(post_types)

    candidates: list[MutantCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    def add(candidate: MutantCandidate | None) -> None:
        if candidate is None:
            return
        key = (candidate.family, candidate.target_rule, candidate.description)
        if key in seen:
            return
        seen.add(key)
        candidates.append(candidate)

    def add_swapped_apply_type(rule, elem: ApplyElement, obligation: str) -> None:
        alternatives = [
            cls_name
            for cls_name in _compatible_class_alternatives(transformation, elem, forbidden_post_types)
            if _class_preserves_apply_link_typing(transformation, rule, elem, cls_name)
        ]
        if not alternatives:
            return
        old_prefix = f"{elem.name} : {elem.class_type}"
        for alternative in alternatives[:MAX_TYPE_SWAP_ALTERNATIVES]:
            new_prefix = f"{elem.name} : {alternative}"
            mutated = _replace_unique_rule_line(
                spec_text,
                rule.name,
                match=lambda line: line.startswith(old_prefix),
                replace=lambda line: line.replace(old_prefix, new_prefix, 1),
            )
            if mutated is None:
                continue
            add(
                MutantCandidate(
                    family="swap_apply_element_type",
                    target_rule=rule.name,
                    obligation=obligation,
                    description=f"{elem.name}: {elem.class_type} -> {alternative}",
                    mutated_text=mutated,
                )
            )

    def add_removed_apply_link(rule, link: ApplyLink, obligation: str) -> None:
        target_line = _line_for_apply_link(rule, link)
        mutated = _replace_unique_rule_line(
            spec_text,
            rule.name,
            match=lambda line: line == target_line,
            replace=_commented,
        )
        if mutated is None:
            return
        add(
            MutantCandidate(
                family="remove_apply_link",
                target_rule=rule.name,
                obligation=obligation,
                description=target_line,
                mutated_text=mutated,
            )
        )

    def add_swapped_apply_assoc(rule, link: ApplyLink, obligation: str) -> None:
        alternatives = _assoc_alternatives(transformation.target_metamodel, str(link.assoc_type))
        if not alternatives:
            return
        target_line = _line_for_apply_link(rule, link)
        mutated = _replace_unique_rule_line(
            spec_text,
            rule.name,
            match=lambda line: line == target_line,
            replace=lambda line: line.replace(f": {link.assoc_type} --", f": {alternatives[0]} --", 1),
        )
        if mutated is None:
            return
        add(
            MutantCandidate(
                family="swap_apply_association",
                target_rule=rule.name,
                obligation=obligation,
                description=f"{link.assoc_type} -> {alternatives[0]}",
                mutated_text=mutated,
            )
        )

    def add_removed_match_link(rule, link: MatchLink, obligation: str) -> None:
        target_line = _line_for_match_link(rule, link)
        mutated = _replace_unique_rule_line(
            spec_text,
            rule.name,
            match=lambda line: line == target_line,
            replace=_commented,
        )
        if mutated is None:
            return
        add(
            MutantCandidate(
                family="remove_match_link",
                target_rule=rule.name,
                obligation=obligation,
                description=target_line,
                mutated_text=mutated,
            )
        )

    def add_swapped_match_assoc(rule, link: MatchLink, obligation: str) -> None:
        alternatives = _assoc_alternatives(transformation.source_metamodel, str(link.assoc_type))
        if not alternatives:
            return
        target_line = _line_for_match_link(rule, link)
        mutated = _replace_unique_rule_line(
            spec_text,
            rule.name,
            match=lambda line: line == target_line,
            replace=lambda line: line.replace(f": {link.assoc_type} --", f": {alternatives[0]} --", 1),
        )
        if mutated is None:
            return
        add(
            MutantCandidate(
                family="swap_match_association",
                target_rule=rule.name,
                obligation=obligation,
                description=f"{link.assoc_type} -> {alternatives[0]}",
                mutated_text=mutated,
            )
        )

    def add_removed_backward(rule, link: BackwardLink, obligation: str) -> None:
        target_line = _line_for_backward_link(rule, link)
        mutated = _replace_unique_rule_line(
            spec_text,
            rule.name,
            match=lambda line: line == target_line,
            replace=_commented,
        )
        if mutated is None:
            return
        add(
            MutantCandidate(
                family="remove_backward_link",
                target_rule=rule.name,
                obligation=obligation,
                description=target_line,
                mutated_text=mutated,
            )
        )

    for post_elem in prop.postcondition.elements:
        traced_from = next((pre_id for post_id, pre_id in prop.postcondition.trace_links if post_id == post_elem.id), None)
        pre_type = str(pre_elem_by_id[traced_from].class_type) if traced_from in pre_elem_by_id else None
        witness_rule = _pick_rule(
            fragment_rules,
            lambda rule: any(str(ae.class_type) == str(post_elem.class_type) for ae in rule.apply_elements)
            and (pre_type is None or any(str(me.class_type) == pre_type for me in rule.match_elements)),
            pre_types,
            post_types,
        )
        if witness_rule is None:
            continue
        witness_elem = next(
            (ae for ae in witness_rule.apply_elements if str(ae.class_type) == str(post_elem.class_type)),
            None,
        )
        if witness_elem is not None:
            add_swapped_apply_type(witness_rule, witness_elem, f"post element `{post_elem.name}`")
        if pre_type is not None:
            for backward in witness_rule.backward_links:
                me = witness_rule.match_element_by_id.get(backward.match_element)
                ae = witness_rule.apply_element_by_id.get(backward.apply_element)
                if me is None or ae is None:
                    continue
                if str(me.class_type) == pre_type and str(ae.class_type) == str(post_elem.class_type):
                    add_removed_backward(witness_rule, backward, f"trace witness for `{post_elem.name}`")
        for match_link in witness_rule.match_links:
            add_removed_match_link(witness_rule, match_link, f"source witness for `{post_elem.name}`")
            add_swapped_match_assoc(witness_rule, match_link, f"source witness for `{post_elem.name}`")

    for post_link in prop.postcondition.links:
        src_elem = post_elem_by_id.get(post_link.source)
        tgt_elem = post_elem_by_id.get(post_link.target)
        if src_elem is None or tgt_elem is None:
            continue
        witness_rule = _pick_rule(
            fragment_rules,
            lambda rule: any(
                str(link.assoc_type) == str(post_link.assoc_type)
                and str(rule.apply_element_by_id[link.source].class_type) == str(src_elem.class_type)
                and str(rule.apply_element_by_id[link.target].class_type) == str(tgt_elem.class_type)
                for link in rule.apply_links
            ),
            pre_types,
            post_types,
        )
        if witness_rule is None:
            continue
        witness_link = next(
            (
                link for link in witness_rule.apply_links
                if str(link.assoc_type) == str(post_link.assoc_type)
                and str(witness_rule.apply_element_by_id[link.source].class_type) == str(src_elem.class_type)
                and str(witness_rule.apply_element_by_id[link.target].class_type) == str(tgt_elem.class_type)
            ),
            None,
        )
        if witness_link is None:
            continue
        add_removed_apply_link(witness_rule, witness_link, f"post link `{post_link.name}`")
        add_swapped_apply_assoc(witness_rule, witness_link, f"post link `{post_link.name}`")

    return candidates[:max_mutants]


def write_results_md(
    summary_rows: list[dict],
    detail_rows: list[dict],
    invalid_rows: list[dict],
    out_path: Path | None = None,
    *,
    max_total_mutants: int | None = None,
) -> None:
    path = out_path or OUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    total_scored = sum(row["scored_mutants"] for row in summary_rows)
    total_agreed = sum(row["agreed_mutants"] for row in summary_rows)
    total_kills = sum(row["joint_kills"] for row in summary_rows)
    total_disagreements = sum(row["disagreements"] for row in summary_rows)
    lines = [
        "# Mutation Testing Results",
        "",
        "Generated by `run_mutation_testing.py`.",
        "This run reuses the same hybrid symbolic verification path as `run_hybrid_cegar_stress.py`,",
        "but scores only semantically valid mutants: the mutated spec must parse, the mutated property must remain in fragment,",
        "and the baseline property must be `HOLDS` both symbolically and concretely before mutation.",
        f"Scored mutants in this run: `{total_scored}`.",
        (
            f"Run cap: at most `{max_total_mutants}` scored mutants."
            if max_total_mutants is not None
            else "Run cap: no global scored-mutant cap."
        ),
        "",
        "## Mutator Families",
        "- `swap_apply_element_type`: changes a witness output element to a different compatible target class.",
        "- `remove_apply_link`: removes a target-side link needed by the postcondition witness.",
        "- `swap_apply_association`: retargets a witness output link to a different valid target association with the same signature.",
        "- `remove_match_link`: removes a source-side structural condition from a witness rule.",
        "- `swap_match_association`: retargets a witness source link to a different valid source association with the same signature.",
        "- `remove_backward_link`: removes an explicit backward reuse edge when the witness depends on one.",
        "",
        "## Global Summary",
        "",
        f"- Agreed mutants: `{total_agreed}`",
        f"- Joint kills: `{total_kills}`",
        f"- Symbolic/concrete disagreements: `{total_disagreements}`",
        "",
        "## Summary By Transformation",
        "",
        "| Transformation | Eligible HOLDS props | Built mutants | Scored mutants | Agreed mutants | Joint kills | Joint survivors | Agreed-only kill rate | Symbolic/concrete disagreements |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary_rows:
        rate = "n/a" if row["agreed_mutants"] == 0 else f"{(100.0 * row['joint_kills'] / row['agreed_mutants']):.1f}%"
        lines.append(
            f"| {row['spec']} | {row['eligible_properties']} | {row['built_mutants']} | {row['scored_mutants']} | {row['agreed_mutants']} | {row['joint_kills']} | {row['joint_survivors']} | {rate} | {row['disagreements']} |"
        )

    lines.extend(
        [
            "",
            "## Detailed Results",
            "",
            "| Transformation | Property | Mutator | Target Rule | Obligation | Symbolic Mutant Result | Concrete Mutant Result | Agreement | Jointly Killed? |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in detail_rows:
        agreement = "✅ Yes" if row["symbolic_result"] == row["concrete_result"] else "❌ No"
        jointly_killed = "✅ Yes" if row["jointly_killed"] else "❌ No"
        lines.append(
            f"| {row['spec']} | {row['property']} | `{row['mutator']}` | {row['target_rule']} | {row['obligation']} | {row['symbolic_result']} | {row['concrete_result']} | {agreement} | {jointly_killed} |"
        )

    if invalid_rows:
        lines.extend(
            [
                "",
                "## Unscored Mutants",
                "",
                "| Transformation | Property | Mutator | Target Rule | Reason |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in invalid_rows:
            lines.append(
                f"| {row['spec']} | {row['property']} | `{row['mutator']}` | {row['target_rule']} | {row['reason']} |"
            )
    lines.extend(["", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _cleanup_mutant_concrete_artifacts(mutant_path: Path) -> None:
    for suffix in ("_out.xmi", "_props.json"):
        artifact = TMP_RESULTS_DIR / f"{mutant_path.stem}{suffix}"
        if artifact.exists():
            artifact.unlink()


def _mutation_probe_input(spec_name: str, prop_name: str, mutant: MutantCandidate) -> tuple[Path | None, bool]:
    if spec_name == "bpmn2petri_concrete.dslt" and prop_name == "StartEventHasToken" and mutant.family == "swap_apply_element_type":
        path = TMP_RESULTS_DIR / "mutation_probe_bpmn_start_event.xmi"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="def1" xsi:type="BPMN:Definitions"/>
  <objects xmi:id="proc1" xsi:type="BPMN:Process"/>
  <links xsi:type="BPMN:processes" source="def1" target="proc1"/>
  <objects xmi:id="se1" xsi:type="BPMN:StartEvent"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="se1"/>
</model>
""",
            encoding="utf-8",
        )
        return path, True
    if spec_name == "bpmn2petri_concrete.dslt" and prop_name == "TaskIsExecutable" and mutant.family == "swap_apply_element_type":
        path = TMP_RESULTS_DIR / "mutation_probe_bpmn_task.xmi"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="def1" xsi:type="BPMN:Definitions"/>
  <objects xmi:id="proc1" xsi:type="BPMN:Process"/>
  <links xsi:type="BPMN:processes" source="def1" target="proc1"/>
  <objects xmi:id="task1" xsi:type="BPMN:Task"/>
  <links xsi:type="BPMN:flowNodes" source="proc1" target="task1"/>
</model>
""",
            encoding="utf-8",
        )
        return path, True
    if spec_name == "uml2java_concrete_canonical.dslt" and prop_name == "ClassHasConstructor" and mutant.family == "swap_apply_element_type":
        path = TMP_RESULTS_DIR / "mutation_probe_uml_constructor.xmi"
        path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<model xmlns:xmi="http://www.omg.org/XMI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <objects xmi:id="model1" xsi:type="UML:Model" name="M1"/>
  <objects xmi:id="pkg1" xsi:type="UML:Package" name="Pkg1"/>
  <objects xmi:id="cls1" xsi:type="UML:Class" name="A" visibility="public" isAbstract="false" isFinal="false" priority="1" layerTag="Core" kind="Entity"/>
  <links xsi:type="UML:rootPackages" source="model1" target="pkg1"/>
  <links xsi:type="UML:packagedElement" source="pkg1" target="cls1"/>
</model>
""",
            encoding="utf-8",
        )
        return path, True
    return None, False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=600_000)
    parser.add_argument("--dependency-mode", default="trace_attr_aware")
    parser.add_argument("--max-mutants-per-property", type=int, default=4)
    parser.add_argument("--max-total-mutants", type=int, default=300)
    parser.add_argument("--specs", nargs="*", default=None, help="Restrict to these spec file names.")
    parser.add_argument("--out", type=str, default=None, help="Output markdown path. Default: docs/evaluation/mutation_testing_results.md")
    args = parser.parse_args()

    MUTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else None
    target_rows = TARGETS if args.specs is None else [row for row in TARGETS if row["spec"].name in set(args.specs)]

    summary_rows: list[dict] = []
    detail_rows: list[dict] = []
    invalid_rows: list[dict] = []
    total_scored = 0

    for target in target_rows:
        if args.max_total_mutants is not None and total_scored >= args.max_total_mutants:
            break
        spec_path = target["spec"]
        input_path = target["input"]()
        spec = parse_dsltrans_file(spec_path)
        baseline_concrete = run_concrete(spec_path, input_path) or {}
        spec_text = spec_path.read_text(encoding="utf-8")

        eligible_properties = 0
        built_mutants = 0
        scored_mutants = 0
        agreed_mutants = 0
        joint_kills = 0
        joint_survivors = 0
        disagreements = 0

        print(f"=== Mutation testing {spec_path.name} ===", flush=True)

        for prop in spec.properties:
            if args.max_total_mutants is not None and total_scored >= args.max_total_mutants:
                break
            baseline_symbolic = verify_property_hybrid(
                spec,
                prop,
                dependency_mode=args.dependency_mode,
                timeout_ms=args.timeout,
            )
            if baseline_symbolic.get("skipped"):
                continue
            if baseline_symbolic["result"] != "HOLDS":
                continue
            if baseline_concrete.get(prop.name) != "HOLDS":
                continue

            eligible_properties += 1
            mutants = build_semantic_mutants(spec_text, spec, prop, max_mutants=args.max_mutants_per_property)
            if args.max_total_mutants is not None:
                remaining = args.max_total_mutants - total_scored
                if remaining <= 0:
                    break
                mutants = mutants[:remaining]
            built_mutants += len(mutants)

            for idx, mutant in enumerate(mutants):
                if args.max_total_mutants is not None and total_scored >= args.max_total_mutants:
                    break
                mutant_path = MUTATIONS_DIR / f"{spec_path.stem}__{prop.name}__m{idx:02d}.dslt"
                mutant_path.write_text(mutant.mutated_text, encoding="utf-8")
                probe_input_path, is_temp_probe_input = _mutation_probe_input(spec_path.name, prop.name, mutant)
                try:
                    try:
                        mutated_spec = parse_dsltrans_file(mutant_path)
                    except Exception as exc:
                        invalid_rows.append(
                            {
                                "spec": spec_path.name,
                                "property": prop.name,
                                "mutator": mutant.family,
                                "target_rule": mutant.target_rule,
                                "reason": f"parse error: {exc}",
                            }
                        )
                        continue

                    mutated_prop = next((p for p in mutated_spec.properties if p.name == prop.name), None)
                    if mutated_prop is None:
                        invalid_rows.append(
                            {
                                "spec": spec_path.name,
                                "property": prop.name,
                                "mutator": mutant.family,
                                "target_rule": mutant.target_rule,
                                "reason": "mutated spec does not contain the target property",
                            }
                        )
                        continue

                    symbolic = verify_property_hybrid(
                        mutated_spec,
                        mutated_prop,
                        dependency_mode=args.dependency_mode,
                        timeout_ms=args.timeout,
                    )
                    if symbolic.get("skipped"):
                        invalid_rows.append(
                            {
                                "spec": spec_path.name,
                                "property": prop.name,
                                "mutator": mutant.family,
                                "target_rule": mutant.target_rule,
                                "reason": "mutated property is not in fragment",
                            }
                        )
                        continue

                    concrete_input_path = probe_input_path if probe_input_path is not None else input_path
                    concrete = run_concrete(mutant_path, concrete_input_path)
                    if concrete is None or prop.name not in concrete:
                        invalid_rows.append(
                            {
                                "spec": spec_path.name,
                                "property": prop.name,
                                "mutator": mutant.family,
                                "target_rule": mutant.target_rule,
                                "reason": "concrete execution failed",
                            }
                        )
                        continue

                    scored_mutants += 1
                    total_scored += 1
                    symbolic_result = symbolic["result"]
                    concrete_result = concrete[prop.name]
                    jointly_killed = symbolic_result == "VIOLATED" and concrete_result == "VIOLATED"
                    jointly_survived = symbolic_result == "HOLDS" and concrete_result == "HOLDS"
                    if jointly_killed:
                        joint_kills += 1
                    if jointly_survived:
                        joint_survivors += 1
                    if symbolic_result != concrete_result:
                        disagreements += 1
                    else:
                        agreed_mutants += 1
                    detail_rows.append(
                        {
                            "spec": spec_path.name,
                            "property": prop.name,
                            "mutator": f"{mutant.family}: {mutant.description}",
                            "target_rule": mutant.target_rule,
                            "obligation": mutant.obligation,
                            "symbolic_result": symbolic_result,
                            "concrete_result": concrete_result,
                            "jointly_killed": jointly_killed,
                        }
                    )
                finally:
                    if mutant_path.exists():
                        mutant_path.unlink()
                    _cleanup_mutant_concrete_artifacts(mutant_path)
                    if is_temp_probe_input and probe_input_path is not None and probe_input_path.exists():
                        probe_input_path.unlink()

        summary_rows.append(
            {
                "spec": spec_path.name,
                "eligible_properties": eligible_properties,
                "built_mutants": built_mutants,
                "scored_mutants": scored_mutants,
                "agreed_mutants": agreed_mutants,
                "joint_kills": joint_kills,
                "joint_survivors": joint_survivors,
                "disagreements": disagreements,
            }
        )
        write_results_md(
            summary_rows,
            detail_rows,
            invalid_rows,
            out_path=out_path,
            max_total_mutants=args.max_total_mutants,
        )

    total_killed = sum(row["joint_kills"] for row in summary_rows)
    print(
        f"Mutation testing complete: scored={total_scored}, jointly killed={total_killed}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
