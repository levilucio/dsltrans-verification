from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import product
from typing import Optional

from .model import (
    ApplyElement,
    AttrRef,
    Attribute,
    BinOp,
    BoolLit,
    Class,
    CompositeProperty,
    Expr,
    FuncCall,
    IntLit,
    ListLit,
    MatchElement,
    Metamodel,
    PairLit,
    Property,
    StringLit,
    Transformation,
    UnaryOp,
    VarRef,
)
from .parser import ParsedSpec


AttrKey = tuple[str, str]
_RefKey = tuple[str, str]
_STRING_OTHER_REPR = "__ABSTRACTION_OTHER__"


@dataclass(frozen=True)
class AttributeOverride:
    string_vocab: Optional[tuple[str, ...]] = None
    int_range: Optional[tuple[int, int]] = None
    note: str = ""


@dataclass(frozen=True)
class AbstractionPolicy:
    metamodel_renames: dict[str, str]
    transformation_renames: dict[str, str]
    attribute_overrides: dict[AttrKey, AttributeOverride]
    default_used_string_vocab: tuple[str, ...] = ("V1", "V2", "OTHER")
    default_unused_string_vocab: tuple[str, ...] = ("OTHER",)
    default_used_int_range: tuple[int, int] = (0, 2)
    default_unused_int_range: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class AttributeDecision:
    metamodel: str
    class_name: str
    attribute_name: str
    concrete_type: str
    abstract_type: str
    decision: str
    reason: str


@dataclass(frozen=True)
class PropertyProjectionDecision:
    property_name: str
    status: str
    reason: str


@dataclass(frozen=True)
class AbstractionResult:
    abstract_spec: ParsedSpec
    attribute_decisions: tuple[AttributeDecision, ...]
    property_decisions: tuple[PropertyProjectionDecision, ...]
    metamodel_mapping: dict[str, str]
    transformation_mapping: dict[str, str]

    def to_json_dict(self) -> dict:
        return {
            "metamodelMapping": self.metamodel_mapping,
            "transformationMapping": self.transformation_mapping,
            "attributeDecisions": [
                {
                    "metamodel": d.metamodel,
                    "className": d.class_name,
                    "attributeName": d.attribute_name,
                    "concreteType": d.concrete_type,
                    "abstractType": d.abstract_type,
                    "decision": d.decision,
                    "reason": d.reason,
                }
                for d in self.attribute_decisions
            ],
            "propertyDecisions": [
                {
                    "propertyName": d.property_name,
                    "status": d.status,
                    "reason": d.reason,
                }
                for d in self.property_decisions
            ],
        }


def make_default_abstraction_policy(spec: ParsedSpec) -> AbstractionPolicy:
    mm_renames: dict[str, str] = {}
    trans_renames: dict[str, str] = {}
    for mm in spec.metamodels:
        if mm.name.endswith("Concrete"):
            mm_renames[mm.name] = mm.name[: -len("Concrete")] + "Proof"
        else:
            mm_renames[mm.name] = mm.name + "Proof"
    for trans in spec.transformations:
        if trans.name.endswith("_concrete"):
            trans_renames[trans.name] = trans.name[: -len("_concrete")] + "_proof"
        else:
            trans_renames[trans.name] = trans.name + "_proof"
    return AbstractionPolicy(
        metamodel_renames=mm_renames,
        transformation_renames=trans_renames,
        attribute_overrides={},
        default_used_string_vocab=("V1", "V2", "OTHER"),
        default_unused_string_vocab=("OTHER",),
        default_used_int_range=(0, 2),
        default_unused_int_range=(0, 0),
    )


@dataclass(frozen=True)
class RuleAbstractionCheck:
    rule_name: str
    location: str
    status: str
    reason: str


@dataclass
class _UsageSummary:
    touched: set[AttrKey]
    string_literals: dict[AttrKey, set[str]]
    int_points: dict[AttrKey, set[int]]
    direct_copy_sources: dict[AttrKey, set[AttrKey]]


@dataclass
class _AttrPlan:
    metamodel_index: int
    class_index: int
    attr_index: int
    declared_key: AttrKey
    alias_keys: frozenset[AttrKey]
    concrete_type: str
    base_attr: Attribute
    local_attr: Attribute
    decision: str
    reason: str
    has_override: bool
    include_local_domain: bool


def _walk_expr(expr: Optional[Expr]):
    if expr is None:
        return
    yield expr
    if isinstance(expr, BinOp):
        yield from _walk_expr(expr.left)
        yield from _walk_expr(expr.right)
    elif isinstance(expr, UnaryOp):
        yield from _walk_expr(expr.operand)
    elif isinstance(expr, FuncCall):
        for arg in expr.args:
            yield from _walk_expr(arg)
    elif isinstance(expr, ListLit):
        for elem in expr.elements:
            yield from _walk_expr(elem)
    elif isinstance(expr, PairLit):
        yield from _walk_expr(expr.fst)
        yield from _walk_expr(expr.snd)


def _record_expr_usage(expr: Optional[Expr], elem_types: dict[str, str], summary: _UsageSummary) -> None:
    if expr is None:
        return

    for node in _walk_expr(expr):
        if isinstance(node, AttrRef):
            key = (elem_types.get(node.element, ""), node.attribute)
            if key[0]:
                summary.touched.add(key)

    for node in _walk_expr(expr):
        if not isinstance(node, BinOp):
            continue
        left_ref = node.left if isinstance(node.left, AttrRef) else None
        right_ref = node.right if isinstance(node.right, AttrRef) else None
        left_str = node.left if isinstance(node.left, StringLit) else None
        right_str = node.right if isinstance(node.right, StringLit) else None
        left_int = node.left if isinstance(node.left, IntLit) else None
        right_int = node.right if isinstance(node.right, IntLit) else None

        if left_ref is not None and right_str is not None:
            key = (elem_types.get(left_ref.element, ""), left_ref.attribute)
            if key[0]:
                summary.string_literals[key].add(right_str.value.strip('"'))
        if right_ref is not None and left_str is not None:
            key = (elem_types.get(right_ref.element, ""), right_ref.attribute)
            if key[0]:
                summary.string_literals[key].add(left_str.value.strip('"'))

        if left_ref is not None and right_int is not None:
            key = (elem_types.get(left_ref.element, ""), left_ref.attribute)
            if key[0]:
                for point in _expand_int_points(node.op, right_int.value, attr_on_left=True):
                    summary.int_points[key].add(point)
        if right_ref is not None and left_int is not None:
            key = (elem_types.get(right_ref.element, ""), right_ref.attribute)
            if key[0]:
                for point in _expand_int_points(node.op, left_int.value, attr_on_left=False):
                    summary.int_points[key].add(point)


def _expand_int_points(op: str, value: int, *, attr_on_left: bool) -> set[int]:
    if op == "==":
        return {value}
    if op == "!=":
        return {value, value + 1}
    if op == ">=":
        return {value - 1, value}
    if op == ">":
        return {value, value + 1} if attr_on_left else {value - 1, value}
    if op == "<=":
        return {value, value + 1}
    if op == "<":
        return {value - 1, value} if attr_on_left else {value, value + 1}
    return {value}


def _collect_usage(spec: ParsedSpec) -> _UsageSummary:
    summary = _UsageSummary(
        touched=set(),
        string_literals=defaultdict(set),
        int_points=defaultdict(set),
        direct_copy_sources=defaultdict(set),
    )

    for trans in spec.transformations:
        for layer in trans.layers:
            for rule in layer.rules:
                match_types = {elem.name: str(elem.class_type) for elem in rule.match_elements}
                apply_types = {elem.name: str(elem.class_type) for elem in rule.apply_elements}
                for elem in rule.match_elements:
                    _record_expr_usage(elem.where_clause, match_types, summary)
                _record_expr_usage(rule.guard, match_types, summary)
                for elem in rule.apply_elements:
                    for binding in elem.attribute_bindings:
                        key = (apply_types.get(elem.name, ""), binding.target.attribute)
                        if key[0]:
                            summary.touched.add(key)
                            if isinstance(binding.value, StringLit):
                                summary.string_literals[key].add(binding.value.value.strip('"'))
                            elif isinstance(binding.value, IntLit):
                                summary.int_points[key].add(binding.value.value)
                            if isinstance(binding.value, AttrRef):
                                src_key = (match_types.get(binding.value.element, ""), binding.value.attribute)
                                if src_key[0]:
                                    summary.direct_copy_sources[key].add(src_key)
                        _record_expr_usage(binding.value, match_types, summary)

    for prop in spec.properties:
        if isinstance(prop, CompositeProperty):
            atomic_props = prop.atomics
        else:
            atomic_props = (prop,)
        for atomic in atomic_props:
            if atomic.precondition is not None:
                pre_types = {elem.name: str(elem.class_type) for elem in atomic.precondition.elements}
                for elem in atomic.precondition.elements:
                    _record_expr_usage(elem.where_clause, pre_types, summary)
                _record_expr_usage(atomic.precondition.constraint, pre_types, summary)
            post_types = {elem.name: str(elem.class_type) for elem in atomic.postcondition.elements}
            _record_expr_usage(atomic.postcondition.constraint, post_types, summary)

    return summary


def _rename_metamodel(mm_name: str, policy: AbstractionPolicy) -> str:
    if mm_name in policy.metamodel_renames:
        return policy.metamodel_renames[mm_name]
    if mm_name.endswith("Concrete"):
        return mm_name[: -len("Concrete")] + "Abstract"
    return mm_name + "Abstract"


def _rename_transformation(name: str, policy: AbstractionPolicy) -> str:
    if name in policy.transformation_renames:
        return policy.transformation_renames[name]
    if name.endswith("_concrete"):
        return name[: -len("_concrete")] + "_proof"
    return name + "_proof"


def _render_abstract_type(attr: Attribute) -> str:
    base = (attr.type or "").strip().lower()
    if base in ("string",) and attr.string_vocab:
        return "String{" + ", ".join(attr.string_vocab) + "}"
    if base in ("int", "integer") and attr.int_range is not None:
        lo, hi = attr.int_range
        return f"Int[{lo}..{hi}]"
    return attr.type


def _attr_base_kind(attr: Attribute) -> str:
    base = (attr.type or "").strip().lower()
    if base in ("string",):
        return "string"
    if base in ("int", "integer"):
        return "int"
    return "other"


def _propagate_direct_copy_domain(
    attr: Attribute,
    local_attr: Attribute,
    include_local_domain: bool,
    source_keys: set[AttrKey],
    usage: _UsageSummary,
    abstract_attrs_by_key: dict[AttrKey, Attribute],
) -> tuple[Attribute, Optional[str]]:
    if not source_keys:
        return local_attr, None

    base_kind = _attr_base_kind(attr)
    if base_kind == "string":
        vocab: list[str] = list(local_attr.string_vocab) if include_local_domain else []
        for source_key in sorted(source_keys):
            source_attr = abstract_attrs_by_key.get(source_key)
            if source_attr is None or _attr_base_kind(source_attr) != "string":
                continue
            for value in source_attr.string_vocab:
                if value not in vocab:
                    vocab.append(value)
        if vocab:
            return (
                replace(local_attr, string_vocab=tuple(vocab), int_range=None),
                "propagated from direct source attribute copy bindings",
            )
    elif base_kind == "int":
        ranges: list[tuple[int, int]] = []
        if include_local_domain and local_attr.int_range is not None:
            ranges.append(local_attr.int_range)
        for source_key in sorted(source_keys):
            source_attr = abstract_attrs_by_key.get(source_key)
            if source_attr is None or _attr_base_kind(source_attr) != "int" or source_attr.int_range is None:
                continue
            ranges.append(source_attr.int_range)
        if ranges:
            lo = min(r[0] for r in ranges)
            hi = max(r[1] for r in ranges)
            return (
                replace(local_attr, int_range=(lo, hi), string_vocab=()),
                "propagated from direct source attribute copy bindings",
            )

    return local_attr, None


def _lookup_attr(mm: Metamodel, class_ref: str, attr_name: str) -> Attribute:
    cls = mm.class_by_id.get(class_ref) or mm.class_by_name.get(class_ref)
    if cls is None:
        raise ValueError(f"Unknown class {class_ref!r} when checking abstraction soundness")
    attr = next((a for a in cls.attributes if a.name == attr_name), None)
    if attr is None:
        raise ValueError(
            f"Unknown attribute {class_ref}.{attr_name!r} when checking abstraction soundness"
        )
    return attr


def _string_literal_value(expr: StringLit) -> str:
    return expr.value.strip('"')


def _int_probe_values(op: str, value: int, *, attr_on_left: bool) -> set[int]:
    if op == "==":
        return {value, value + 1}
    if op == "!=":
        return {value, value + 1}
    if op == ">=":
        return {value - 1, value} if attr_on_left else {value, value + 1}
    if op == ">":
        return {value, value + 1} if attr_on_left else {value - 1, value}
    if op == "<=":
        return {value, value + 1} if attr_on_left else {value - 1, value}
    if op == "<":
        return {value - 1, value} if attr_on_left else {value, value + 1}
    return {value, value + 1}


def _bool_probe_values(_op: str, value: bool) -> set[bool]:
    return {value, not value}


def _note_expr_ref_candidates(
    expr: Optional[Expr],
    elem_types: dict[str, str],
    concrete_mm: Metamodel,
    out: dict[_RefKey, set[object]],
) -> None:
    if expr is None:
        return
    for node in _walk_expr(expr):
        if isinstance(node, AttrRef):
            key = (node.element, node.attribute)
            attr = _lookup_attr(concrete_mm, elem_types[node.element], node.attribute)
            if _attr_base_kind(attr) == "other":
                base = (attr.type or "").strip().lower()
                if base in ("bool", "boolean"):
                    out.setdefault(key, set()).update({True, False})
                elif attr.type in concrete_mm.enum_by_name:
                    out.setdefault(key, set()).update(concrete_mm.enum_by_name[attr.type].literals)
                else:
                    raise ValueError(
                        f"Unsupported rule-abstraction check for {elem_types[node.element]}.{node.attribute} "
                        f"of type {attr.type!r}"
                    )

    for node in _walk_expr(expr):
        if not isinstance(node, BinOp):
            continue
        if node.op in ("&&", "||", "+", "-", "*", "/", "%"):
            continue
        left_ref = node.left if isinstance(node.left, AttrRef) else None
        right_ref = node.right if isinstance(node.right, AttrRef) else None
        if left_ref is not None and right_ref is not None:
            raise ValueError(
                f"Unsupported rule-abstraction check for attribute-to-attribute comparison "
                f"{left_ref.element}.{left_ref.attribute} {node.op} {right_ref.element}.{right_ref.attribute}"
            )
        if left_ref is None and right_ref is None:
            continue
        ref = left_ref or right_ref
        assert ref is not None
        key = (ref.element, ref.attribute)
        candidates = out.setdefault(key, set())
        literal = node.right if left_ref is not None else node.left
        attr_on_left = left_ref is not None
        if isinstance(literal, StringLit):
            candidates.update({_string_literal_value(literal), _STRING_OTHER_REPR})
        elif isinstance(literal, IntLit):
            candidates.update(_int_probe_values(node.op, literal.value, attr_on_left=attr_on_left))
        elif isinstance(literal, BoolLit):
            candidates.update(_bool_probe_values(node.op, literal.value))
        elif literal is not None:
            raise ValueError(
                f"Unsupported rule-abstraction check literal in comparison {node.op!r}: "
                f"{type(literal).__name__}"
            )


def _eval_expr(expr: Expr, env: dict[_RefKey, object]) -> object:
    if isinstance(expr, IntLit):
        return expr.value
    if isinstance(expr, BoolLit):
        return expr.value
    if isinstance(expr, StringLit):
        return _string_literal_value(expr)
    if isinstance(expr, AttrRef):
        return env[(expr.element, expr.attribute)]
    if isinstance(expr, UnaryOp):
        operand = _eval_expr(expr.operand, env)
        if expr.op == "!":
            return not bool(operand)
        if expr.op == "-":
            return -int(operand)
        raise ValueError(f"Unsupported unary operator in rule-abstraction check: {expr.op!r}")
    if isinstance(expr, BinOp):
        left = _eval_expr(expr.left, env)
        right = _eval_expr(expr.right, env)
        if expr.op == "&&":
            return bool(left) and bool(right)
        if expr.op == "||":
            return bool(left) or bool(right)
        if expr.op == "==":
            return left == right
        if expr.op == "!=":
            return left != right
        if expr.op == "<":
            return left < right
        if expr.op == "<=":
            return left <= right
        if expr.op == ">":
            return left > right
        if expr.op == ">=":
            return left >= right
        if expr.op == "+":
            return left + right
        if expr.op == "-":
            return left - right
        if expr.op == "*":
            return left * right
        if expr.op == "/":
            return left / right
        if expr.op == "%":
            return left % right
        raise ValueError(f"Unsupported binary operator in rule-abstraction check: {expr.op!r}")
    raise ValueError(
        f"Unsupported expression in rule-abstraction check: {type(expr).__name__}"
    )


def _value_allowed_in_abstract_domain(value: object, attr: Attribute, abstract_mm: Metamodel) -> bool:
    base = (attr.type or "").strip().lower()
    if base == "string":
        return value in attr.string_vocab
    if base in ("int", "integer"):
        if attr.int_range is None or not isinstance(value, int):
            return False
        lo, hi = attr.int_range
        return lo <= value <= hi
    if base in ("bool", "boolean"):
        return isinstance(value, bool)
    if attr.type in abstract_mm.enum_by_name:
        return str(value) in abstract_mm.enum_by_name[attr.type].literals
    return True


def _expr_truth_values(
    expr: Expr,
    elem_types: dict[str, str],
    concrete_mm: Metamodel,
    abstract_mm: Metamodel,
) -> tuple[set[bool], set[bool]]:
    candidates: dict[_RefKey, set[object]] = {}
    _note_expr_ref_candidates(expr, elem_types, concrete_mm, candidates)
    if not candidates:
        truth = bool(_eval_expr(expr, {}))
        return ({truth}, {truth})

    for element, attr_name in list(candidates.keys()):
        abstract_attr = _lookup_attr(abstract_mm, elem_types[element], attr_name)
        base = (abstract_attr.type or "").strip().lower()
        if base == "string":
            candidates[(element, attr_name)].update(abstract_attr.string_vocab)
        elif base in ("int", "integer") and abstract_attr.int_range is not None:
            lo, hi = abstract_attr.int_range
            candidates[(element, attr_name)].update({lo, hi})
        elif base in ("bool", "boolean"):
            candidates[(element, attr_name)].update({True, False})
        elif abstract_attr.type in abstract_mm.enum_by_name:
            candidates[(element, attr_name)].update(abstract_mm.enum_by_name[abstract_attr.type].literals)

    ref_keys = sorted(candidates.keys())
    value_lists = [sorted(values, key=repr) for _, values in sorted(candidates.items())]
    concrete_truths: set[bool] = set()
    abstract_truths: set[bool] = set()
    for assignment in product(*value_lists):
        env = dict(zip(ref_keys, assignment))
        truth = bool(_eval_expr(expr, env))
        concrete_truths.add(truth)
        if all(
            _value_allowed_in_abstract_domain(
                value,
                _lookup_attr(abstract_mm, elem_types[element], attr_name),
                abstract_mm,
            )
            for (element, attr_name), value in env.items()
        ):
            abstract_truths.add(truth)
    return concrete_truths, abstract_truths


def _validate_rule_abstraction_soundness(
    concrete_spec: ParsedSpec,
    abstract_spec: ParsedSpec,
) -> tuple[RuleAbstractionCheck, ...]:
    checks: list[RuleAbstractionCheck] = []
    if len(concrete_spec.transformations) != len(abstract_spec.transformations):
        raise ValueError("Abstraction soundness check requires aligned transformation lists")

    for concrete_trans, abstract_trans in zip(
        concrete_spec.transformations,
        abstract_spec.transformations,
    ):
        if len(concrete_trans.layers) != len(abstract_trans.layers):
            raise ValueError(
                f"Abstraction soundness check requires aligned layers for transformation {concrete_trans.name}"
            )
        for concrete_layer, abstract_layer in zip(concrete_trans.layers, abstract_trans.layers):
            if len(concrete_layer.rules) != len(abstract_layer.rules):
                raise ValueError(
                    f"Abstraction soundness check requires aligned rules in layer {concrete_layer.name}"
                )
            for concrete_rule, _abstract_rule in zip(concrete_layer.rules, abstract_layer.rules):
                elem_types = {me.name: str(me.class_type) for me in concrete_rule.match_elements}
                for match_elem in concrete_rule.match_elements:
                    if match_elem.where_clause is None:
                        continue
                    concrete_truths, abstract_truths = _expr_truth_values(
                        match_elem.where_clause,
                        elem_types,
                        concrete_trans.source_metamodel,
                        abstract_trans.source_metamodel,
                    )
                    if concrete_truths != abstract_truths:
                        checks.append(
                            RuleAbstractionCheck(
                                rule_name=concrete_rule.name,
                                location=f"where({match_elem.name})",
                                status="failed",
                                reason=(
                                    f"truth partition changed from {sorted(concrete_truths)} "
                                    f"to {sorted(abstract_truths)}"
                                ),
                            )
                        )
                if concrete_rule.guard is not None:
                    concrete_truths, abstract_truths = _expr_truth_values(
                        concrete_rule.guard,
                        elem_types,
                        concrete_trans.source_metamodel,
                        abstract_trans.source_metamodel,
                    )
                    if concrete_truths != abstract_truths:
                        checks.append(
                            RuleAbstractionCheck(
                                rule_name=concrete_rule.name,
                                location="guard",
                                status="failed",
                                reason=(
                                    f"truth partition changed from {sorted(concrete_truths)} "
                                    f"to {sorted(abstract_truths)}"
                                ),
                            )
                        )
    return tuple(checks)


def synthesize_abstract_spec(spec: ParsedSpec, policy: AbstractionPolicy) -> AbstractionResult:
    usage = _collect_usage(spec)
    decisions: list[AttributeDecision] = []
    attr_plans: list[_AttrPlan] = []

    mm_map: dict[str, str] = {}
    new_mms: list[Metamodel] = []
    for mm_index, mm in enumerate(spec.metamodels):
        new_mm_name = _rename_metamodel(mm.name, policy)
        mm_map[mm.name] = new_mm_name
        new_classes: list[Class] = []
        for class_index, cls in enumerate(mm.classes):
            new_attrs: list[Attribute] = []
            for attr_index, attr in enumerate(cls.attributes):
                key = (cls.name, attr.name)
                subtype_ids = mm.get_subtypes(cls.id)
                subtype_keys = {
                    (sub.name, attr.name)
                    for sub in mm.classes
                    if sub.id in subtype_ids
                }
                usage_keys = {key, *subtype_keys}
                override = policy.attribute_overrides.get(key)
                concrete_type = attr.type
                new_attr = attr
                decision = "unchanged"
                reason = "non-attribute or already finite"

                attr_type_lower = (attr.type or "").strip().lower()
                if override is not None:
                    if override.string_vocab is not None:
                        new_attr = replace(attr, string_vocab=override.string_vocab, int_range=None)
                        decision = "override"
                        reason = override.note or "case-study override"
                    elif override.int_range is not None:
                        new_attr = replace(attr, int_range=override.int_range, string_vocab=())
                        decision = "override"
                        reason = override.note or "case-study override"
                elif attr_type_lower == "string":
                    literal_set: set[str] = set()
                    touched = False
                    for sk in usage_keys:
                        literal_set.update(usage.string_literals.get(sk, set()))
                        touched = touched or (sk in usage.touched)
                    literals = tuple(sorted(literal_set))
                    if literals:
                        vocab = list(literals)
                        if "OTHER" not in vocab:
                            vocab.append("OTHER")
                        new_attr = replace(attr, string_vocab=tuple(vocab))
                        decision = "finite_vocab"
                        reason = "derived from observed string literals plus OTHER"
                    elif touched:
                        new_attr = replace(attr, string_vocab=policy.default_used_string_vocab)
                        decision = "canonical_vocab"
                        reason = "attribute is touched by rules/properties; keep alias-supporting finite domain"
                    else:
                        new_attr = replace(attr, string_vocab=policy.default_unused_string_vocab)
                        decision = "singleton_vocab"
                        reason = "attribute unused by rules/properties; keep explicit but collapsed domain"
                elif attr_type_lower in ("int", "integer"):
                    points: set[int] = set()
                    touched = False
                    for sk in usage_keys:
                        points.update(usage.int_points.get(sk, set()))
                        touched = touched or (sk in usage.touched)
                    if points:
                        lo = min(points)
                        hi = max(points)
                        new_attr = replace(attr, int_range=(lo, hi))
                        decision = "bounded_range"
                        reason = "derived from observed integer thresholds/comparisons"
                    elif touched:
                        new_attr = replace(attr, int_range=policy.default_used_int_range)
                        decision = "default_used_range"
                        reason = "attribute is touched by rules/properties; use small finite default range"
                    else:
                        new_attr = replace(attr, int_range=policy.default_unused_int_range)
                        decision = "singleton_range"
                        reason = "attribute unused by rules/properties; keep explicit but collapsed range"
                attr_plans.append(
                    _AttrPlan(
                        metamodel_index=mm_index,
                        class_index=class_index,
                        attr_index=attr_index,
                        declared_key=key,
                        alias_keys=frozenset(usage_keys),
                        concrete_type=concrete_type,
                        base_attr=attr,
                        local_attr=new_attr,
                        decision=decision,
                        reason=reason,
                        has_override=override is not None,
                        include_local_domain=decision in {"finite_vocab", "bounded_range"},
                    )
                )
                new_attrs.append(new_attr)
            new_classes.append(replace(cls, attributes=tuple(new_attrs)))
        new_mms.append(replace(mm, name=new_mm_name, classes=tuple(new_classes)))

    current_attrs_by_declared: dict[AttrKey, Attribute] = {
        plan.declared_key: plan.local_attr for plan in attr_plans
    }
    current_attrs_by_usage_key: dict[AttrKey, Attribute] = {}
    plan_by_declared: dict[AttrKey, _AttrPlan] = {}
    for plan in attr_plans:
        plan_by_declared[plan.declared_key] = plan
        for alias_key in plan.alias_keys:
            current_attrs_by_usage_key.setdefault(alias_key, plan.local_attr)

    changed = True
    while changed:
        changed = False
        for plan in attr_plans:
            if plan.has_override:
                continue
            source_keys: set[AttrKey] = set()
            for alias_key in plan.alias_keys:
                source_keys.update(usage.direct_copy_sources.get(alias_key, set()))
            propagated_attr, propagated_reason = _propagate_direct_copy_domain(
                plan.base_attr,
                current_attrs_by_declared[plan.declared_key],
                plan.include_local_domain,
                source_keys,
                usage,
                current_attrs_by_usage_key,
            )
            if propagated_reason is None:
                continue
            if propagated_attr != current_attrs_by_declared[plan.declared_key]:
                current_attrs_by_declared[plan.declared_key] = propagated_attr
                for alias_key in plan.alias_keys:
                    current_attrs_by_usage_key[alias_key] = propagated_attr
                changed = True

    rebuilt_mms: list[Metamodel] = []
    for mm_index, mm in enumerate(new_mms):
        rebuilt_classes: list[Class] = []
        for class_index, cls in enumerate(mm.classes):
            rebuilt_attrs: list[Attribute] = []
            for attr_index, attr in enumerate(cls.attributes):
                plan = next(
                    p for p in attr_plans
                    if p.metamodel_index == mm_index and p.class_index == class_index and p.attr_index == attr_index
                )
                final_attr = current_attrs_by_declared[plan.declared_key]
                final_decision = plan.decision
                final_reason = plan.reason
                if (not plan.has_override) and final_attr != plan.local_attr:
                    final_decision = "propagated_copy_domain"
                    final_reason = "propagated through attribute copy dependency graph"
                decisions.append(
                    AttributeDecision(
                        metamodel=mm.name,
                        class_name=cls.name,
                        attribute_name=plan.base_attr.name,
                        concrete_type=plan.concrete_type,
                        abstract_type=_render_abstract_type(final_attr),
                        decision=final_decision,
                        reason=final_reason,
                    )
                )
                rebuilt_attrs.append(final_attr)
            rebuilt_classes.append(replace(cls, attributes=tuple(rebuilt_attrs)))
        rebuilt_mms.append(replace(mm, classes=tuple(rebuilt_classes)))

    new_mm_by_old = {old.name: new for old, new in zip(spec.metamodels, rebuilt_mms)}
    trans_map: dict[str, str] = {}
    new_transformations: list[Transformation] = []
    for trans in spec.transformations:
        new_name = _rename_transformation(trans.name, policy)
        trans_map[trans.name] = new_name
        new_transformations.append(
            replace(
                trans,
                name=new_name,
                source_metamodel=new_mm_by_old[trans.source_metamodel.name],
                target_metamodel=new_mm_by_old[trans.target_metamodel.name],
            )
        )

    property_decisions = tuple(
        PropertyProjectionDecision(
            property_name=getattr(prop, "name", str(prop)),
            status="exact",
            reason="all classes, associations, and referenced attributes are preserved; only domains are finite-ized",
        )
        for prop in spec.properties
    )

    abstract_spec = ParsedSpec(
        metamodels=tuple(rebuilt_mms),
        transformations=tuple(new_transformations),
        properties=spec.properties,
    )
    rule_checks = _validate_rule_abstraction_soundness(spec, abstract_spec)
    if rule_checks:
        problems = "; ".join(
            f"rule {check.rule_name} {check.location}: {check.reason}"
            for check in rule_checks[:5]
        )
        raise ValueError(
            "Attribute abstraction failed rule-level soundness validation for guards/where clauses: "
            f"{problems}"
        )
    return AbstractionResult(
        abstract_spec=abstract_spec,
        attribute_decisions=tuple(decisions),
        property_decisions=property_decisions,
        metamodel_mapping=mm_map,
        transformation_mapping=trans_map,
    )


def synthesize_abstract_spec_for_property(
    spec: ParsedSpec,
    policy: AbstractionPolicy,
    property_name: str,
) -> AbstractionResult:
    property_obj = next((prop for prop in spec.properties if getattr(prop, "name", None) == property_name), None)
    if property_obj is None:
        raise ValueError(f"Unknown property: {property_name}")
    property_only_spec = ParsedSpec(
        metamodels=spec.metamodels,
        transformations=spec.transformations,
        properties=(property_obj,),
    )
    return synthesize_abstract_spec(property_only_spec, policy)
