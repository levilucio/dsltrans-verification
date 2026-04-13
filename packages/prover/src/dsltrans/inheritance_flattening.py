from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import product
from typing import Dict, Iterable, Optional

from .model import (
    ApplyElement,
    ApplyLink,
    Association,
    AssocId,
    Class,
    ClassId,
    ElementId,
    Layer,
    MatchElement,
    MatchLink,
    Metamodel,
    PostCondition,
    PreCondition,
    Property,
    Rule,
    RuleId,
    Transformation,
)
from .parser import ParsedSpec


def _effective_attributes(mm: Metamodel, cls: Class) -> tuple:
    attrs = []
    seen: set[str] = set()
    current: Optional[Class] = cls
    while current is not None:
        for attr in current.attributes:
            if attr.name in seen:
                continue
            seen.add(attr.name)
            attrs.append(attr)
        if current.parent is None:
            break
        current = mm.class_by_id.get(current.parent)
    return tuple(attrs)


def _is_same_or_subtype(mm: Metamodel, actual: ClassId, expected: ClassId) -> bool:
    if actual == expected:
        return True
    current = mm.class_by_id.get(actual)
    while current is not None and current.parent is not None:
        parent = mm.class_by_id.get(current.parent)
        if parent is None:
            break
        if parent.id == expected:
            return True
        current = parent
    return False


def _concrete_options(mm: Metamodel, class_id: ClassId) -> tuple[ClassId, ...]:
    out: list[ClassId] = []
    for c in mm.classes:
        if c.is_abstract:
            continue
        if _is_same_or_subtype(mm, c.id, class_id):
            out.append(c.id)
    return tuple(out)


def _class_uses_inheritance(mm: Metamodel, class_id: ClassId) -> bool:
    cls = mm.class_by_id[class_id]
    if cls.is_abstract:
        return True
    opts = _concrete_options(mm, class_id)
    return len(opts) > 1 or (len(opts) == 1 and opts[0] != class_id)


def _flat_assoc_name(orig_name: str, src_name: str, tgt_name: str) -> str:
    return f"__flat__{orig_name}__{src_name}__{tgt_name}"


def _flat_rule_name(rule_name: str, suffix_parts: Iterable[str]) -> str:
    suffix = "__".join(suffix_parts)
    return f"__flat__{rule_name}__{suffix}" if suffix else rule_name


def _flat_property_id(prop_id: str, index: int) -> str:
    return f"__flat__{prop_id}__{index}"


def _flatten_metamodel(
    mm: Metamodel,
) -> tuple[Metamodel, dict[tuple[str, str, str], str], dict[str, str]]:
    flat_classes = tuple(
        replace(c, is_abstract=False, parent=None, attributes=_effective_attributes(mm, c))
        for c in mm.classes
        if not c.is_abstract
    )
    assoc_lookup: dict[tuple[str, str, str], str] = {}
    assoc_origin_map: dict[str, str] = {}
    flat_assocs: list[Association] = []
    for assoc in mm.associations:
        src_opts = _concrete_options(mm, assoc.source_class)
        tgt_opts = _concrete_options(mm, assoc.target_class)
        preserve_name = (
            len(src_opts) == 1
            and len(tgt_opts) == 1
            and src_opts[0] == assoc.source_class
            and tgt_opts[0] == assoc.target_class
        )
        for src_cls in src_opts:
            for tgt_cls in tgt_opts:
                assoc_name = (
                    assoc.name
                    if preserve_name
                    else _flat_assoc_name(assoc.name, str(src_cls), str(tgt_cls))
                )
                assoc_lookup[(assoc.name, str(src_cls), str(tgt_cls))] = assoc_name
                assoc_origin_map[assoc_name] = assoc.name
                flat_assocs.append(
                    replace(
                        assoc,
                        id=AssocId(assoc_name),
                        name=assoc_name,
                        source_class=src_cls,
                        target_class=tgt_cls,
                    )
                )
    return (
        Metamodel(name=mm.name, classes=flat_classes, associations=tuple(flat_assocs), enums=mm.enums),
        assoc_lookup,
        assoc_origin_map,
    )


@dataclass(frozen=True)
class FlattenedTransformationBundle:
    transformation: Transformation
    metamodels: tuple[Metamodel, ...]
    source_assoc_lookup: dict[tuple[str, str, str], str]
    target_assoc_lookup: dict[tuple[str, str, str], str]
    assoc_origin_map: dict[str, str]
    rule_name_map: dict[str, str]


@lru_cache(maxsize=32)
def flatten_transformation(transformation: Transformation) -> FlattenedTransformationBundle:
    flat_src_mm, source_assoc_lookup, source_origin_map = _flatten_metamodel(
        transformation.source_metamodel
    )
    flat_tgt_mm, target_assoc_lookup, target_origin_map = _flatten_metamodel(
        transformation.target_metamodel
    )
    flat_layers: list[Layer] = []
    rule_name_map: dict[str, str] = {}

    for layer in transformation.layers:
        flat_rules: list[Rule] = []
        for rule in layer.rules:
            match_options = [
                [(me.id, opt) for opt in _concrete_options(transformation.source_metamodel, me.class_type)]
                for me in rule.match_elements
            ]
            apply_options = [
                [(ae.id, opt) for opt in _concrete_options(transformation.target_metamodel, ae.class_type)]
                for ae in rule.apply_elements
            ]
            if any(len(opts) == 0 for opts in match_options + apply_options):
                continue

            for combo in product(*match_options, *apply_options):
                type_map = {elem_id: cls_id for elem_id, cls_id in combo}

                valid = True
                for link in rule.match_links:
                    src_cls = type_map[link.source]
                    tgt_cls = type_map[link.target]
                    if (
                        link.assoc_type not in transformation.source_metamodel.assoc_by_id
                        and str(link.assoc_type) not in transformation.source_metamodel.assoc_by_name
                    ):
                        valid = False
                        break
                    assoc = transformation.source_metamodel.assoc_by_name[str(link.assoc_type)]
                    if not (
                        _is_same_or_subtype(
                            transformation.source_metamodel, src_cls, assoc.source_class
                        )
                        and _is_same_or_subtype(
                            transformation.source_metamodel, tgt_cls, assoc.target_class
                        )
                    ):
                        valid = False
                        break
                if not valid:
                    continue

                for link in rule.apply_links:
                    src_cls = type_map[link.source]
                    tgt_cls = type_map[link.target]
                    assoc = transformation.target_metamodel.assoc_by_name[str(link.assoc_type)]
                    if not (
                        _is_same_or_subtype(
                            transformation.target_metamodel, src_cls, assoc.source_class
                        )
                        and _is_same_or_subtype(
                            transformation.target_metamodel, tgt_cls, assoc.target_class
                        )
                    ):
                        valid = False
                        break
                if not valid:
                    continue

                match_elements = tuple(
                    replace(me, class_type=type_map[me.id]) for me in rule.match_elements
                )
                apply_elements = tuple(
                    replace(ae, class_type=type_map[ae.id]) for ae in rule.apply_elements
                )
                match_links = tuple(
                    replace(
                        ml,
                        assoc_type=AssocId(
                            source_assoc_lookup[
                                (str(ml.assoc_type), str(type_map[ml.source]), str(type_map[ml.target]))
                            ]
                        ),
                    )
                    for ml in rule.match_links
                )
                apply_links = tuple(
                    replace(
                        al,
                        assoc_type=AssocId(
                            target_assoc_lookup[
                                (str(al.assoc_type), str(type_map[al.source]), str(type_map[al.target]))
                            ]
                        ),
                    )
                    for al in rule.apply_links
                )
                varying_parts = [
                    f"{elem.name}_{type_map[elem.id]}"
                    for elem in (*rule.match_elements, *rule.apply_elements)
                    if _class_uses_inheritance(
                        transformation.source_metamodel
                        if isinstance(elem, MatchElement)
                        else transformation.target_metamodel,
                        elem.class_type,
                    )
                ]
                flat_name = _flat_rule_name(rule.name, varying_parts)
                flat_id = RuleId(flat_name)
                rule_name_map[flat_name] = rule.name
                flat_rules.append(
                    replace(
                        rule,
                        id=flat_id,
                        name=flat_name,
                        match_elements=match_elements,
                        match_links=match_links,
                        apply_elements=apply_elements,
                        apply_links=apply_links,
                    )
                )

        flat_layers.append(replace(layer, rules=tuple(flat_rules)))

    flat_transformation = replace(
        transformation,
        source_metamodel=flat_src_mm,
        target_metamodel=flat_tgt_mm,
        layers=tuple(flat_layers),
    )
    assoc_origin_map = {**source_origin_map, **target_origin_map}
    return FlattenedTransformationBundle(
        transformation=flat_transformation,
        metamodels=(flat_src_mm, flat_tgt_mm),
        source_assoc_lookup=source_assoc_lookup,
        target_assoc_lookup=target_assoc_lookup,
        assoc_origin_map=assoc_origin_map,
        rule_name_map=rule_name_map,
    )


def _rule_requires_flattening(transformation: Transformation, rule: Rule) -> bool:
    for me in rule.match_elements:
        if _class_uses_inheritance(transformation.source_metamodel, me.class_type):
            return True
    for ae in rule.apply_elements:
        if _class_uses_inheritance(transformation.target_metamodel, ae.class_type):
            return True
    for link in rule.match_links:
        assoc = transformation.source_metamodel.assoc_by_name[str(link.assoc_type)]
        src_cls = rule.match_element_by_id[link.source].class_type
        tgt_cls = rule.match_element_by_id[link.target].class_type
        if src_cls != assoc.source_class or tgt_cls != assoc.target_class:
            return True
    for link in rule.apply_links:
        assoc = transformation.target_metamodel.assoc_by_name[str(link.assoc_type)]
        src_cls = rule.apply_element_by_id[link.source].class_type
        tgt_cls = rule.apply_element_by_id[link.target].class_type
        if src_cls != assoc.source_class or tgt_cls != assoc.target_class:
            return True
    return False


def _property_requires_flattening(transformation: Transformation, prop: Property) -> bool:
    if prop.precondition is not None:
        pre_by_id = {e.id: e for e in prop.precondition.elements}
        for e in prop.precondition.elements:
            if _class_uses_inheritance(transformation.source_metamodel, e.class_type):
                return True
        for link in prop.precondition.links:
            assoc = transformation.source_metamodel.assoc_by_name[str(link.assoc_type)]
            src_cls = pre_by_id[link.source].class_type
            tgt_cls = pre_by_id[link.target].class_type
            if src_cls != assoc.source_class or tgt_cls != assoc.target_class:
                return True
    post_by_id = {e.id: e for e in prop.postcondition.elements}
    for e in prop.postcondition.elements:
        if _class_uses_inheritance(transformation.target_metamodel, e.class_type):
            return True
    for link in prop.postcondition.links:
        assoc = transformation.target_metamodel.assoc_by_name[str(link.assoc_type)]
        src_cls = post_by_id[link.source].class_type
        tgt_cls = post_by_id[link.target].class_type
        if src_cls != assoc.source_class or tgt_cls != assoc.target_class:
            return True
    return False


def spec_property_needs_flattening(spec: ParsedSpec, prop: Property) -> bool:
    if not spec.transformations:
        return False
    transformation = spec.transformations[0]
    if not hasattr(transformation, "source_metamodel") or not hasattr(transformation, "target_metamodel"):
        return False
    if not (
        any(c.parent is not None for c in transformation.source_metamodel.classes)
        or any(c.parent is not None for c in transformation.target_metamodel.classes)
    ):
        return False
    return any(_rule_requires_flattening(transformation, rule) for rule in transformation.all_rules) or _property_requires_flattening(
        transformation, prop
    )


def _expand_property(
    transformation: Transformation,
    flat_bundle: FlattenedTransformationBundle,
    prop: Property,
) -> tuple[Property, ...]:
    pre = prop.precondition
    pre_options = []
    if pre is not None:
        pre_options = [
            [(e.id, opt) for opt in _concrete_options(transformation.source_metamodel, e.class_type)]
            for e in pre.elements
        ]
    post = prop.postcondition
    post_options = [
        [(e.id, opt) for opt in _concrete_options(transformation.target_metamodel, e.class_type)]
        for e in post.elements
    ]
    if any(len(opts) == 0 for opts in pre_options + post_options):
        return ()

    combos = product(*pre_options, *post_options) if (pre_options or post_options) else [()]
    expanded: list[Property] = []
    for index, combo in enumerate(combos):
        type_map = {elem_id: cls_id for elem_id, cls_id in combo}

        valid = True
        if pre is not None:
            for link in pre.links:
                assoc = transformation.source_metamodel.assoc_by_name[str(link.assoc_type)]
                src_cls = type_map[link.source]
                tgt_cls = type_map[link.target]
                if not (
                    _is_same_or_subtype(transformation.source_metamodel, src_cls, assoc.source_class)
                    and _is_same_or_subtype(transformation.source_metamodel, tgt_cls, assoc.target_class)
                ):
                    valid = False
                    break
        if not valid:
            continue
        for link in post.links:
            assoc = transformation.target_metamodel.assoc_by_name[str(link.assoc_type)]
            src_cls = type_map[link.source]
            tgt_cls = type_map[link.target]
            if not (
                _is_same_or_subtype(transformation.target_metamodel, src_cls, assoc.source_class)
                and _is_same_or_subtype(transformation.target_metamodel, tgt_cls, assoc.target_class)
            ):
                valid = False
                break
        if not valid:
            continue

        flat_pre: Optional[PreCondition] = None
        if pre is not None:
            flat_pre = replace(
                pre,
                elements=tuple(replace(e, class_type=type_map[e.id]) for e in pre.elements),
                links=tuple(
                    replace(
                        link,
                        assoc_type=AssocId(
                            flat_bundle.source_assoc_lookup[
                                (str(link.assoc_type), str(type_map[link.source]), str(type_map[link.target]))
                            ]
                        ),
                    )
                    for link in pre.links
                ),
            )
        flat_post = replace(
            post,
            elements=tuple(replace(e, class_type=type_map[e.id]) for e in post.elements),
            links=tuple(
                replace(
                    link,
                    assoc_type=AssocId(
                        flat_bundle.target_assoc_lookup[
                            (str(link.assoc_type), str(type_map[link.source]), str(type_map[link.target]))
                        ]
                    ),
                )
                for link in post.links
            ),
        )
        expanded.append(
            replace(
                prop,
                id=_flat_property_id(prop.id, index),
                precondition=flat_pre,
                postcondition=flat_post,
            )
        )
    return tuple(expanded)


@dataclass(frozen=True)
class FlattenedPropertyBundle:
    variants: tuple["FlattenedPropertyVariant", ...]
    rule_name_map: dict[str, str]
    assoc_origin_map: dict[str, str]
    original_transformation: Transformation
    applied: bool


@dataclass(frozen=True)
class FlattenedPropertyVariant:
    spec: ParsedSpec
    property: Property


def _find_injective_mapping(
    prop_elements: tuple[MatchElement | ApplyElement, ...],
    rule_elements: tuple[MatchElement | ApplyElement, ...],
    prop_links: tuple[MatchLink | ApplyLink, ...],
    rule_links: tuple[MatchLink | ApplyLink, ...],
) -> Optional[dict[ElementId, ElementId]]:
    rule_by_id = {elem.id: elem for elem in rule_elements}
    candidates = {
        elem.id: [cand.id for cand in rule_elements if cand.class_type == elem.class_type]
        for elem in prop_elements
    }
    if any(not ids for ids in candidates.values()):
        return None

    rule_link_sigs = {
        (str(link.assoc_type), link.source, link.target)
        for link in rule_links
    }
    ordered_prop_ids = sorted(candidates, key=lambda elem_id: len(candidates[elem_id]))
    mapping: dict[ElementId, ElementId] = {}
    used_rule_ids: set[ElementId] = set()

    def backtrack(index: int) -> Optional[dict[ElementId, ElementId]]:
        if index == len(ordered_prop_ids):
            for link in prop_links:
                mapped = (
                    str(link.assoc_type),
                    mapping[link.source],
                    mapping[link.target],
                )
                if mapped not in rule_link_sigs:
                    return None
            return dict(mapping)
        prop_id = ordered_prop_ids[index]
        for rule_id in candidates[prop_id]:
            if rule_id in used_rule_ids:
                continue
            mapping[prop_id] = rule_id
            used_rule_ids.add(rule_id)
            result = backtrack(index + 1)
            if result is not None:
                return result
            used_rule_ids.remove(rule_id)
            del mapping[prop_id]
        return None

    return backtrack(0)


def _rule_matches_property_topology(rule: Rule, flat_prop: Property) -> bool:
    if flat_prop.precondition is None:
        pre_mapping: dict[ElementId, ElementId] = {}
    else:
        pre_mapping = _find_injective_mapping(
            flat_prop.precondition.elements,
            rule.match_elements,
            flat_prop.precondition.links,
            rule.match_links,
        )
        if pre_mapping is None:
            return False

    post_mapping = _find_injective_mapping(
        flat_prop.postcondition.elements,
        rule.apply_elements,
        flat_prop.postcondition.links,
        rule.apply_links,
    )
    if post_mapping is None:
        return False

    backward_by_apply = {bl.apply_element: bl.match_element for bl in rule.backward_links}
    for post_elem_id, pre_elem_id in flat_prop.postcondition.trace_links:
        apply_id = post_mapping.get(post_elem_id)
        match_id = pre_mapping.get(pre_elem_id)
        if apply_id is None or match_id is None:
            return False
        if apply_id in backward_by_apply:
            if backward_by_apply[apply_id] != match_id:
                return False
    return True


def _rule_signature(rule: Rule) -> tuple[set[ClassId], set[tuple[str, ClassId, ClassId]], set[tuple[ClassId, ClassId]], set[tuple[ClassId, ClassId]], set[ClassId]]:
    backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
    produced_types = {ae.class_type for ae in rule.apply_elements if ae.id not in backward_apply_ids}
    produced_links = {
        (str(link.assoc_type), rule.apply_element_by_id[link.source].class_type, rule.apply_element_by_id[link.target].class_type)
        for link in rule.apply_links
    }
    produced_traces = {
        (me.class_type, ae.class_type)
        for me in rule.match_elements
        for ae in rule.apply_elements
        if ae.id not in backward_apply_ids
    }
    backward_requirements = {
        (
            rule.match_element_by_id[bl.match_element].class_type,
            rule.apply_element_by_id[bl.apply_element].class_type,
        )
        for bl in rule.backward_links
        if bl.match_element in rule.match_element_by_id and bl.apply_element in rule.apply_element_by_id
    }
    backward_types = {pair[1] for pair in backward_requirements}
    return produced_types, produced_links, produced_traces, backward_requirements, backward_types


def _property_needs(flat_prop: Property) -> tuple[set[ClassId], set[tuple[str, ClassId, ClassId]], set[tuple[ClassId, ClassId]]]:
    post_by_id = {e.id: e for e in flat_prop.postcondition.elements}
    traced_post_ids = {post_elem_id for post_elem_id, _ in flat_prop.postcondition.trace_links}
    linked_post_ids = {
        elem_id
        for link in flat_prop.postcondition.links
        for elem_id in (link.source, link.target)
    }
    needed_types = {
        e.class_type
        for e in flat_prop.postcondition.elements
        if e.id not in traced_post_ids and e.id not in linked_post_ids
    }
    needed_links = {
        (str(link.assoc_type), post_by_id[link.source].class_type, post_by_id[link.target].class_type)
        for link in flat_prop.postcondition.links
        if link.source in post_by_id and link.target in post_by_id
    }
    needed_traces: set[tuple[ClassId, ClassId]] = set()
    if flat_prop.precondition is not None:
        pre_by_id = {e.id: e for e in flat_prop.precondition.elements}
        for post_elem_id, pre_elem_id in flat_prop.postcondition.trace_links:
            post_elem = post_by_id.get(post_elem_id)
            pre_elem = pre_by_id.get(pre_elem_id)
            if post_elem is not None and pre_elem is not None:
                needed_traces.add((pre_elem.class_type, post_elem.class_type))
    return needed_types, needed_links, needed_traces


def _prune_flat_transformation_for_property(
    transformation: Transformation,
    flat_prop: Property,
) -> Transformation:
    target_rules: set[RuleId] = set()
    rule_signatures: dict[RuleId, tuple[set[ClassId], set[tuple[str, ClassId, ClassId]], set[tuple[ClassId, ClassId]], set[tuple[ClassId, ClassId]], set[ClassId]]] = {}
    rule_layers: dict[RuleId, int] = {}
    for layer_index, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            rule_layers[rule.id] = layer_index
            signature = _rule_signature(rule)
            rule_signatures[rule.id] = signature
            if _rule_matches_property_topology(rule, flat_prop):
                target_rules.add(rule.id)

    kept_rule_ids: set[RuleId] = set()
    support_types: dict[ClassId, int] = {}
    support_traces: dict[tuple[ClassId, ClassId], int] = {}
    for layer in transformation.layers:
        for rule in layer.rules:
            if rule.id not in target_rules:
                continue
            _, _, _, backward_requirements, backward_types = rule_signatures[rule.id]
            kept_rule_ids.add(rule.id)
            rule_layer = rule_layers[rule.id]
            for cls in backward_types:
                support_types[cls] = max(support_types.get(cls, -1), rule_layer)
            for pair in backward_requirements:
                support_traces[pair] = max(support_traces.get(pair, -1), rule_layer)

    changed = bool(target_rules)
    while changed:
        changed = False
        for layer_index, layer in reversed(list(enumerate(transformation.layers))):
            for rule in layer.rules:
                if rule.id in kept_rule_ids:
                    continue
                produced_types, _, produced_traces, backward_requirements, backward_types = rule_signatures[rule.id]
                type_supported = any(
                    layer_index < support_types.get(produced_type, -1)
                    for produced_type in produced_types
                )
                trace_supported = any(
                    layer_index < support_traces.get(produced_trace, -1)
                    for produced_trace in produced_traces
                )
                if not (type_supported or trace_supported):
                    continue
                kept_rule_ids.add(rule.id)
                before = (dict(support_types), dict(support_traces))
                for cls in backward_types:
                    support_types[cls] = max(support_types.get(cls, -1), layer_index)
                for pair in backward_requirements:
                    support_traces[pair] = max(support_traces.get(pair, -1), layer_index)
                if support_types != before[0] or support_traces != before[1]:
                    changed = True

    new_layers = []
    for layer in transformation.layers:
        kept_rules = tuple(r for r in layer.rules if r.id in kept_rule_ids)
        if kept_rules:
            new_layers.append(replace(layer, rules=kept_rules))
    return replace(transformation, layers=tuple(new_layers))


def flatten_spec_for_property(spec: ParsedSpec, prop: Property) -> FlattenedPropertyBundle:
    if not spec.transformations:
        raise ValueError("No transformation found in specification")
    transformation = spec.transformations[0]
    if not spec_property_needs_flattening(spec, prop):
        if not hasattr(spec, "metamodels"):
            return FlattenedPropertyBundle(
                variants=(FlattenedPropertyVariant(spec=spec, property=prop),),
                rule_name_map={},
                assoc_origin_map={},
                original_transformation=transformation,
                applied=False,
            )
        return FlattenedPropertyBundle(
            variants=(
                FlattenedPropertyVariant(
                    spec=spec.__class__(
                        metamodels=spec.metamodels,
                        transformations=spec.transformations,
                        properties=(prop,),
                    ),
                    property=prop,
                ),
            ),
            rule_name_map={},
            assoc_origin_map={},
            original_transformation=transformation,
            applied=False,
        )

    flat_transformation = flatten_transformation(transformation)
    flat_properties = _expand_property(transformation, flat_transformation, prop)
    variants = []
    for flat_prop in flat_properties:
        pruned_trans = _prune_flat_transformation_for_property(
            flat_transformation.transformation,
            flat_prop,
        )
        flat_spec = spec.__class__(
            metamodels=flat_transformation.metamodels,
            transformations=(pruned_trans,),
            properties=(flat_prop,),
        )
        variants.append(FlattenedPropertyVariant(spec=flat_spec, property=flat_prop))
    return FlattenedPropertyBundle(
        variants=tuple(variants),
        rule_name_map=flat_transformation.rule_name_map,
        assoc_origin_map=flat_transformation.assoc_origin_map,
        original_transformation=transformation,
        applied=True,
    )


def lift_counterexample(
    counterexample: Optional[dict],
    *,
    original_transformation: Transformation,
    rule_name_map: dict[str, str],
    assoc_origin_map: dict[str, str],
) -> Optional[dict]:
    if not isinstance(counterexample, dict):
        return counterexample
    out = {
        "source_elements": dict(counterexample.get("source_elements", {}) or {}),
        "target_elements": dict(counterexample.get("target_elements", {}) or {}),
        "source_links": {},
        "target_links": {},
        "rule_firings": [],
    }

    for key, pairs in (counterexample.get("source_links", {}) or {}).items():
        orig = assoc_origin_map.get(key, key)
        out["source_links"].setdefault(orig, [])
        out["source_links"][orig].extend(pairs)
    for key, pairs in (counterexample.get("target_links", {}) or {}).items():
        orig = assoc_origin_map.get(key, key)
        out["target_links"].setdefault(orig, [])
        out["target_links"][orig].extend(pairs)

    for firing in counterexample.get("rule_firings", []) or []:
        rule_name = str(firing.get("rule", ""))
        out["rule_firings"].append(
            {
                **firing,
                "rule": rule_name_map.get(rule_name, rule_name),
            }
        )

    for mm, bucket_name in (
        (original_transformation.source_metamodel, "source_elements"),
        (original_transformation.target_metamodel, "target_elements"),
    ):
        bucket = out[bucket_name]
        for cls in mm.classes:
            if cls.name in bucket:
                continue
            union: set[int] = set()
            for concrete in _concrete_options(mm, cls.id):
                union.update(bucket.get(str(concrete), []))
            if union:
                bucket[cls.name] = sorted(union)

    return out
