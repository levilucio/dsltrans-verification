"""
Cutoff theorem support for DSLTrans verification.

- Fragment checker: F-LNR (transformations) and G-BPP (properties).
- Property-specific cutoff bound: K = c·(m+p)·d·(a+1) with minimal K via relevant rules/classes.
- R3 (stratified rules) is assumed via DSLTrans semantics and is not enforced by the checker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .model import (
    Transformation,
    Property,
    Rule,
    RuleId,
    ClassId,
    PreCondition,
    PostCondition,
    MatchLink,
    LinkKind,
    Metamodel,
    Class,
    Attribute,
    Expr,
    AttrRef,
    BinOp,
    UnaryOp,
    FuncCall,
    IntLit,
    BoolLit,
    StringLit,
    ListLit,
    PairLit,
)
from .optimizations import compute_rule_dependencies, compute_rule_dependencies_trace_aware, RuleDependencyGraph


# -----------------------------------------------------------------------------
# Fragment violations (F-LNR and G-BPP)
# -----------------------------------------------------------------------------

@dataclass
class FragmentViolation:
    """A single fragment violation."""
    rule_id: str  # "(R1)", "(R2)", "(R4)", "(R5)", or "G-BPP"
    reason: str
    rule_name: Optional[str] = None
    location: Optional[str] = None
    details: Optional[dict] = None


# -----------------------------------------------------------------------------
# Fragment checker (F-LNR + G-BPP)
# -----------------------------------------------------------------------------

DEFAULT_MAX_MATCH_SIZE = 4
DEFAULT_MAX_PROPERTY_PATTERN_SIZE = 5


def check_fragment(
    transformation: Transformation,
    property: Property,
    max_match_size: int = DEFAULT_MAX_MATCH_SIZE,
    max_property_pattern_size: int = DEFAULT_MAX_PROPERTY_PATTERN_SIZE,
) -> tuple[bool, list[FragmentViolation]]:
    """
    Check if (transformation, property) is in the F-LNR × G-BPP fragment.

    Returns (True, []) if valid; (False, violations) otherwise.
    R3 (stratified rules) is not checked: DSLTrans layer structure and rule
    application order provide implicit stratification (rules in the same layer
    have independent match patterns; backward links only reference earlier
    layers), so the theorem's assumption is satisfied by the language.
    """
    violations: list[FragmentViolation] = []

    # ---- F-LNR ----

    # (R1) No indirect links in rules
    for layer in transformation.layers:
        for rule in layer.rules:
            for link in rule.match_links:
                if link.kind == LinkKind.INDIRECT:
                    violations.append(FragmentViolation(
                        rule_id="(R1)",
                        reason=f"Indirect link in match: {link.name}",
                        rule_name=rule.name,
                    ))
                    break

    # (R1) No indirect links in property precondition
    if property.precondition:
        for link in property.precondition.links:
            if link.kind == LinkKind.INDIRECT:
                violations.append(FragmentViolation(
                    rule_id="(R1)",
                    reason=f"Indirect link in property precondition: {link.name}",
                    location="property precondition",
                ))
                break

    # (R1) No indirect links in property postcondition
    # Postcondition links are typically ApplyLink (direct only), but we keep this
    # defensive check so future parser/model extensions that allow indirect links
    # are rejected by fragment checking.
    for link in property.postcondition.links:
        if getattr(link, "kind", LinkKind.DIRECT) == LinkKind.INDIRECT:
            violations.append(FragmentViolation(
                rule_id="(R1)",
                reason=f"Indirect link in property postcondition: {link.name}",
                location="property postcondition",
            ))
            break

    # (R2) Bounded match size
    for layer in transformation.layers:
        for rule in layer.rules:
            n = len(rule.match_elements)
            if n > max_match_size:
                violations.append(FragmentViolation(
                    rule_id="(R2)",
                    reason=f"Match size {n} exceeds {max_match_size}",
                    rule_name=rule.name,
                    details={"match_size": n, "max_allowed": max_match_size},
                ))

    # (R4) Acyclic backward dependencies
    dep_graph = compute_rule_dependencies(transformation)
    if _has_cycle(dep_graph):
        violations.append(FragmentViolation(
            rule_id="(R4)",
            reason="Cyclic backward link dependencies detected",
        ))

    # (R5) Finite attribute domains (source + target metamodels)
    src_enum_names = {e.name for e in transformation.source_metamodel.enums}
    tgt_enum_names = {e.name for e in transformation.target_metamodel.enums}
    for mm, enum_names, mm_label in (
        (transformation.source_metamodel, src_enum_names, "source"),
        (transformation.target_metamodel, tgt_enum_names, "target"),
    ):
        for cls in mm.classes:
            for attr in cls.attributes:
                if not _has_finite_domain(attr, enum_names):
                    violations.append(FragmentViolation(
                        rule_id="(R5)",
                        reason=f"Unbounded or non-finite attribute: {attr.name}",
                        details={
                            "metamodel": mm_label,
                            "class": cls.name,
                            "attribute": attr.name,
                            "type": attr.type,
                            "int_range": attr.int_range,
                            "string_vocab_size": len(attr.string_vocab),
                        },
                    ))

    # ---- G-BPP ----

    if property.precondition:
        pre_size = len(property.precondition.elements)
        if pre_size > max_property_pattern_size:
            violations.append(FragmentViolation(
                rule_id="G-BPP",
                reason=f"Precondition pattern size {pre_size} exceeds {max_property_pattern_size}",
                location="precondition",
                details={"size": pre_size, "max_allowed": max_property_pattern_size},
            ))

    post_size = len(property.postcondition.elements)
    if post_size > max_property_pattern_size:
        violations.append(FragmentViolation(
            rule_id="G-BPP",
            reason=f"Postcondition pattern size {post_size} exceeds {max_property_pattern_size}",
            location="postcondition",
            details={"size": post_size, "max_allowed": max_property_pattern_size},
        ))

    return (len(violations) == 0, violations)


def _has_finite_domain(attr: Attribute, enum_names: set[str] | None = None) -> bool:
    """Finite domain check for R5: Bool, enum, bounded Int, finite String vocab."""
    enum_names = enum_names or set()
    t = (attr.type or "").strip().lower()
    if t in ("bool", "boolean"):
        return True
    # Explicit enum declaration reference
    if (attr.type or "").strip() in enum_names:
        return True
    # Legacy enum naming conventions
    if t.startswith("enum") or "enum" in t:
        return True
    if t in ("int", "integer"):
        # Int is finite iff bounded range is declared
        return attr.int_range is not None
    if t == "string":
        # String is finite iff explicit finite vocabulary is declared
        return len(attr.string_vocab) > 0
    if t in ("real", "float"):
        return False
    return False


def _has_cycle(dep_graph: RuleDependencyGraph) -> bool:
    """Detect cycle in rule dependency graph via DFS."""
    visited: set[RuleId] = set()
    rec_stack: set[RuleId] = set()

    def dfs(rule_id: RuleId) -> bool:
        visited.add(rule_id)
        rec_stack.add(rule_id)
        for dep_id in dep_graph.dependencies.get(rule_id, frozenset()):
            if dep_id not in visited:
                if dfs(dep_id):
                    return True
            elif dep_id in rec_stack:
                return True
        rec_stack.discard(rule_id)
        return False

    for rule_id in dep_graph.dependencies:
        if rule_id not in visited and dfs(rule_id):
            return True
    return False


# -----------------------------------------------------------------------------
# Attribute-aware analysis helpers
# -----------------------------------------------------------------------------

@dataclass
class _VarConstraint:
    """Conservative constraints for one (class, attribute)."""
    eq_values: set[object] = field(default_factory=set)
    neq_values: set[object] = field(default_factory=set)
    int_lower: Optional[int] = None
    int_upper: Optional[int] = None

    def add_lower(self, v: int) -> None:
        self.int_lower = v if self.int_lower is None else max(self.int_lower, v)

    def add_upper(self, v: int) -> None:
        self.int_upper = v if self.int_upper is None else min(self.int_upper, v)

    def definitely_unsat(self) -> bool:
        if len(self.eq_values) > 1:
            return True
        if self.eq_values and any(v in self.neq_values for v in self.eq_values):
            return True
        if self.int_lower is not None and self.int_upper is not None and self.int_lower > self.int_upper:
            return True
        if self.eq_values:
            v = next(iter(self.eq_values))
            if isinstance(v, int):
                if self.int_lower is not None and v < self.int_lower:
                    return True
                if self.int_upper is not None and v > self.int_upper:
                    return True
        return False


@dataclass
class _AttrSummary:
    """Read/write keys and conservative satisfiability summary for expressions."""
    reads: set[tuple[ClassId, str]] = field(default_factory=set)
    writes: set[tuple[ClassId, str]] = field(default_factory=set)
    constraints: dict[tuple[ClassId, str], _VarConstraint] = field(default_factory=dict)

    @property
    def touched(self) -> set[tuple[ClassId, str]]:
        return self.reads | self.writes | set(self.constraints.keys())

    def definitely_unsat(self) -> bool:
        return any(c.definitely_unsat() for c in self.constraints.values())


def _expr_walk(expr: Optional[Expr]):
    if expr is None:
        return
    yield expr
    if isinstance(expr, BinOp):
        yield from _expr_walk(expr.left)
        yield from _expr_walk(expr.right)
    elif isinstance(expr, UnaryOp):
        yield from _expr_walk(expr.operand)
    elif isinstance(expr, FuncCall):
        for a in expr.args:
            yield from _expr_walk(a)
    elif isinstance(expr, ListLit):
        for e in expr.elements:
            yield from _expr_walk(e)
    elif isinstance(expr, PairLit):
        yield from _expr_walk(expr.fst)
        yield from _expr_walk(expr.snd)


def _literal_value(expr: Expr) -> Optional[object]:
    if isinstance(expr, IntLit):
        return expr.value
    if isinstance(expr, BoolLit):
        return expr.value
    if isinstance(expr, StringLit):
        return expr.value
    return None


def _attr_key(ref: AttrRef, elem_type: dict[str, ClassId]) -> Optional[tuple[ClassId, str]]:
    cls = elem_type.get(ref.element)
    if cls is None:
        return None
    return (cls, ref.attribute)


def _record_expr_reads(
    expr: Optional[Expr],
    elem_type: dict[str, ClassId],
    out: _AttrSummary,
) -> None:
    for n in _expr_walk(expr):
        if isinstance(n, AttrRef):
            k = _attr_key(n, elem_type)
            if k is not None:
                out.reads.add(k)


def _record_expr_constraints(
    expr: Optional[Expr],
    elem_type: dict[str, ClassId],
    out: _AttrSummary,
) -> None:
    if expr is None:
        return
    for n in _expr_walk(expr):
        if not isinstance(n, BinOp):
            continue
        op = n.op
        if op not in ("==", "!=", "<", "<=", ">", ">="):
            continue
        left_ref = n.left if isinstance(n.left, AttrRef) else None
        right_ref = n.right if isinstance(n.right, AttrRef) else None
        left_lit = _literal_value(n.left)
        right_lit = _literal_value(n.right)

        # attr op literal
        if left_ref is not None and right_lit is not None:
            key = _attr_key(left_ref, elem_type)
            lit = right_lit
            attr_on_left = True
        # literal op attr
        elif right_ref is not None and left_lit is not None:
            key = _attr_key(right_ref, elem_type)
            lit = left_lit
            attr_on_left = False
        else:
            continue
        if key is None:
            continue
        c = out.constraints.setdefault(key, _VarConstraint())
        out.reads.add(key)

        if op == "==":
            c.eq_values.add(lit)
        elif op == "!=":
            c.neq_values.add(lit)
        elif isinstance(lit, int):
            # Normalize literal-on-left form by flipping inequalities.
            if attr_on_left:
                if op == "<":
                    c.add_upper(lit - 1)
                elif op == "<=":
                    c.add_upper(lit)
                elif op == ">":
                    c.add_lower(lit + 1)
                elif op == ">=":
                    c.add_lower(lit)
            else:
                if op == "<":
                    c.add_lower(lit + 1)   # lit < attr
                elif op == "<=":
                    c.add_lower(lit)       # lit <= attr
                elif op == ">":
                    c.add_upper(lit - 1)   # lit > attr
                elif op == ">=":
                    c.add_upper(lit)       # lit >= attr


def _merge_constraint_compat(
    a: dict[tuple[ClassId, str], _VarConstraint],
    b: dict[tuple[ClassId, str], _VarConstraint],
) -> bool:
    keys = set(a.keys()) | set(b.keys())
    for k in keys:
        c1 = a.get(k, _VarConstraint())
        c2 = b.get(k, _VarConstraint())
        merged = _VarConstraint(
            eq_values=set(c1.eq_values) | set(c2.eq_values),
            neq_values=set(c1.neq_values) | set(c2.neq_values),
            int_lower=c1.int_lower,
            int_upper=c1.int_upper,
        )
        if c2.int_lower is not None:
            merged.add_lower(c2.int_lower)
        if c2.int_upper is not None:
            merged.add_upper(c2.int_upper)
        if merged.definitely_unsat():
            return False
    return True


def _rule_attr_summary(rule: Rule) -> _AttrSummary:
    elem_type = {me.name: me.class_type for me in rule.match_elements}
    out = _AttrSummary()
    # Reads and constraints from match where clauses
    for me in rule.match_elements:
        _record_expr_reads(me.where_clause, elem_type, out)
        _record_expr_constraints(me.where_clause, elem_type, out)
    # Reads and constraints from guard
    _record_expr_reads(rule.guard, elem_type, out)
    _record_expr_constraints(rule.guard, elem_type, out)
    # Apply bindings: write target attr, read any attrs used in RHS
    for ae in rule.apply_elements:
        for b in ae.attribute_bindings:
            out.writes.add((ae.class_type, b.target.attribute))
            _record_expr_reads(b.value, elem_type, out)
            _record_expr_constraints(b.value, elem_type, out)
    return out


def _property_attr_summary(property: Property) -> _AttrSummary:
    out = _AttrSummary()
    if not property.precondition:
        return out
    elem_type = {e.name: e.class_type for e in property.precondition.elements}
    for e in property.precondition.elements:
        _record_expr_reads(e.where_clause, elem_type, out)
        _record_expr_constraints(e.where_clause, elem_type, out)
    if property.precondition.constraint is not None:
        _record_expr_reads(property.precondition.constraint, elem_type, out)
        _record_expr_constraints(property.precondition.constraint, elem_type, out)
    return out


# -----------------------------------------------------------------------------
# Property-specific cutoff bound
# -----------------------------------------------------------------------------

def _relevant_rules(transformation: Transformation, property: Property) -> set[RuleId]:
    """Rules that can contribute to the property: create postcondition types + backward deps."""
    post_types = {e.class_type for e in property.postcondition.elements}
    post_assocs = {str(link.assoc_type) for link in property.postcondition.links}
    type_producers: dict = {}
    link_producers: dict[str, set[RuleId]] = {}
    for layer in transformation.layers:
        for rule in layer.rules:
            backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
            for ae in rule.apply_elements:
                if ae.id not in backward_apply_ids:
                    tid = ae.class_type
                    if tid not in type_producers:
                        type_producers[tid] = set()
                    type_producers[tid].add(rule.id)
                elif rule.apply_links:
                    # Link-only rule (all apply elements are backward links), or a rule that 
                    # creates links between backward elements. We must register it as a producer 
                    # so that properties requiring these types/links can slice it in.
                    tid = ae.class_type
                    if tid not in type_producers:
                        type_producers[tid] = set()
                    type_producers[tid].add(rule.id)
            for al in rule.apply_links:
                link_producers.setdefault(str(al.assoc_type), set()).add(rule.id)

    relevant = set()
    worklist = set()
    for tid in post_types:
        worklist.update(type_producers.get(tid, set()))
    for assoc_name in post_assocs:
        worklist.update(link_producers.get(assoc_name, set()))
    while worklist:
        rule_id = worklist.pop()
        if rule_id in relevant:
            continue
        relevant.add(rule_id)
        rule = next(
            (r for layer in transformation.layers for r in layer.rules if r.id == rule_id),
            None,
        )
        if rule is None:
            continue
        for bl in rule.backward_links:
            ae = rule.apply_element_by_id.get(bl.apply_element)
            if ae is None:
                continue
            required_type = ae.class_type
            for prod_id in type_producers.get(required_type, set()):
                if prod_id not in relevant:
                    worklist.add(prod_id)
    return relevant


def _relevant_rules_trace_aware(transformation: Transformation, property: Property) -> set[RuleId]:
    """
    Trace-aware relevant-rule computation.

    Legacy relevant-rule closure follows backward links by adding *any* producer
    of the required target type. This can grossly over-approximate in large specs.

    Here we refine producers using strict backward-link semantics with implicit
    cartesian traces for newly-created apply elements: every match element type S
    traces to every newly-created apply element type T. A backward link requiring
    (S -> T) therefore only pulls in rules that can create T and have S in match.
    """
    post_types = {e.class_type for e in property.postcondition.elements}
    post_assocs = {str(link.assoc_type) for link in property.postcondition.links}

    type_producers: dict[ClassId, set[RuleId]] = {}
    trace_producers: dict[tuple[ClassId, ClassId], set[RuleId]] = {}
    link_producers: dict[str, set[RuleId]] = {}

    for layer in transformation.layers:
        for rule in layer.rules:
            backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
            apply_types = {
                ae.class_type for ae in rule.apply_elements
                if ae.id not in backward_apply_ids
            }
            match_types = {me.class_type for me in rule.match_elements}
            for t in apply_types:
                type_producers.setdefault(t, set()).add(rule.id)
                for s in match_types:
                    trace_producers.setdefault((s, t), set()).add(rule.id)
            for al in rule.apply_links:
                link_producers.setdefault(str(al.assoc_type), set()).add(rule.id)

    relevant: set[RuleId] = set()
    worklist: set[RuleId] = set()
    
    traced_post_elements = set()
    for tgt_id, src_id in property.postcondition.trace_links:
        tgt_elem = next((e for e in property.postcondition.elements if e.id == tgt_id), None)
        src_elem = next((e for e in property.precondition.elements if e.id == src_id), None)
        if tgt_elem and src_elem:
            worklist.update(trace_producers.get((src_elem.class_type, tgt_elem.class_type), set()))
            traced_post_elements.add(tgt_id)
            
    for e in property.postcondition.elements:
        if e.id not in traced_post_elements:
            worklist.update(type_producers.get(e.class_type, set()))
    for assoc_name in post_assocs:
        worklist.update(link_producers.get(assoc_name, set()))

    rule_by_id = {r.id: r for r in transformation.all_rules}

    while worklist:
        rule_id = worklist.pop()
        if rule_id in relevant:
            continue
        relevant.add(rule_id)
        rule = rule_by_id.get(rule_id)
        if rule is None:
            continue
        for bl in rule.backward_links:
            ae = rule.apply_element_by_id.get(bl.apply_element)
            me = rule.match_element_by_id.get(bl.match_element)
            if ae is None or me is None:
                continue
            required_t = ae.class_type
            required_s = me.class_type
            candidates = trace_producers.get((required_s, required_t), set())
            for prod_id in candidates:
                if prod_id not in relevant:
                    worklist.add(prod_id)
    return relevant


def _relevant_rules_trace_attr_aware(transformation: Transformation, property: Property) -> set[RuleId]:
    """
    Trace-aware relevance refined by attribute constraints/footprints.

    Conservative policy:
    - Start from trace-aware structural producer closure.
    - Prefer producer candidates that are
      (a) locally satisfiable,
      (b) constraint-compatible with property attribute constraints, and
      (c) attribute-relevant to the property (touch property attrs),
      but fallback to structural candidates when filtering would empty the set.
    """
    post_types = {e.class_type for e in property.postcondition.elements}
    post_assocs = {str(link.assoc_type) for link in property.postcondition.links}
    prop_attr = _property_attr_summary(property)
    prop_keys = prop_attr.touched

    rule_by_id = {r.id: r for r in transformation.all_rules}
    rule_attr = {rid: _rule_attr_summary(r) for rid, r in rule_by_id.items()}

    type_producers: dict[ClassId, set[RuleId]] = {}
    trace_producers: dict[tuple[ClassId, ClassId], set[RuleId]] = {}
    link_producers: dict[str, set[RuleId]] = {}
    for layer in transformation.layers:
        for rule in layer.rules:
            backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
            apply_types = {
                ae.class_type for ae in rule.apply_elements
                if ae.id not in backward_apply_ids
            }
            match_types = {me.class_type for me in rule.match_elements}
            for t in apply_types:
                type_producers.setdefault(t, set()).add(rule.id)
                for s in match_types:
                    trace_producers.setdefault((s, t), set()).add(rule.id)
            for al in rule.apply_links:
                link_producers.setdefault(str(al.assoc_type), set()).add(rule.id)

    def _attr_filter(cands: set[RuleId]) -> set[RuleId]:
        if not cands:
            return cands
        # 1) remove rules proven unsat by local constraints
        sat = {rid for rid in cands if not rule_attr[rid].definitely_unsat()}
        if sat:
            cands = sat
        # 2) keep only rules compatible with property constraints, if any remain
        compat = {
            rid for rid in cands
            if _merge_constraint_compat(rule_attr[rid].constraints, prop_attr.constraints)
        }
        if compat:
            cands = compat
        return cands

    relevant: set[RuleId] = set()
    worklist: set[RuleId] = set()
    
    traced_post_elements = set()
    for tgt_id, src_id in property.postcondition.trace_links:
        tgt_elem = next((e for e in property.postcondition.elements if e.id == tgt_id), None)
        src_elem = next((e for e in property.precondition.elements if e.id == src_id), None)
        if tgt_elem and src_elem:
            cands = trace_producers.get((src_elem.class_type, tgt_elem.class_type), set())
            filtered = _attr_filter(set(cands))
            worklist.update(filtered if filtered else cands)
            traced_post_elements.add(tgt_id)
            
    for e in property.postcondition.elements:
        if e.id not in traced_post_elements:
            cands = type_producers.get(e.class_type, set())
            filtered = _attr_filter(set(cands))
            worklist.update(filtered if filtered else cands)
    for assoc_name in post_assocs:
        cands = link_producers.get(assoc_name, set())
        filtered = _attr_filter(set(cands))
        worklist.update(filtered if filtered else cands)

    while worklist:
        rule_id = worklist.pop()
        if rule_id in relevant:
            continue
        relevant.add(rule_id)
        rule = rule_by_id.get(rule_id)
        if rule is None:
            continue
        for bl in rule.backward_links:
            ae = rule.apply_element_by_id.get(bl.apply_element)
            me = rule.match_element_by_id.get(bl.match_element)
            if ae is None or me is None:
                continue
            required_t = ae.class_type
            required_s = me.class_type
            candidates = set(trace_producers.get((required_s, required_t), set()))
            filtered = _attr_filter(candidates)
            for prod_id in (filtered if filtered else candidates):
                if prod_id not in relevant:
                    worklist.add(prod_id)
    return relevant


def _dependency_depth(dep_graph: RuleDependencyGraph, rule_ids: set[RuleId]) -> int:
    """
    Longest path length in the dependency subgraph (rule A depends on B => edge A -> B).
    Depth of a node = 0 if no deps, else 1 + max(depth of dependency). Return max over nodes.
    """
    if not rule_ids:
        return 0
    deps = {rid: dep_graph.dependencies.get(rid, frozenset()) & rule_ids for rid in rule_ids}
    depth: dict[RuleId, int] = {}

    def depth_of(rid: RuleId) -> int:
        if rid in depth:
            return depth[rid]
        preds = deps.get(rid, frozenset())
        if not preds:
            depth[rid] = 0
            return 0
        d = 1 + max(depth_of(d) for d in preds)
        depth[rid] = d
        return d

    for rid in rule_ids:
        depth_of(rid)
    return max(depth.values(), default=0)


def _path_aware_rules_for_depth(
    transformation: Transformation,
    property: Property,
    dep_graph: RuleDependencyGraph,
    relevant_rule_ids: set[RuleId],
) -> set[RuleId]:
    """
    Compute a property-path-aware subset of rules for depth `d`.

    Keeps rules that lie on at least one dependency path from:
      - a precondition-compatible seed rule (matches a precondition type), to
      - a postcondition-anchor rule (creates a postcondition type).

    Falls back conservatively to `relevant_rule_ids` if anchors/seeds cannot
    be established or the intersection becomes empty.
    """
    if not relevant_rule_ids:
        return set()

    rule_by_id = {r.id: r for r in transformation.all_rules}
    post_types = {e.class_type for e in property.postcondition.elements}
    pre_types = (
        {e.class_type for e in property.precondition.elements}
        if property.precondition
        else set()
    )

    anchors: set[RuleId] = set()
    for rid in relevant_rule_ids:
        rule = rule_by_id.get(rid)
        if rule is None:
            continue
        backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
        created_types = {
            ae.class_type for ae in rule.apply_elements if ae.id not in backward_apply_ids
        }
        if created_types & post_types:
            anchors.add(rid)
    if not anchors:
        return set(relevant_rule_ids)

    seeds: set[RuleId] = set()
    if pre_types:
        for rid in relevant_rule_ids:
            rule = rule_by_id.get(rid)
            if rule is None:
                continue
            match_types = {me.class_type for me in rule.match_elements}
            if match_types & pre_types:
                seeds.add(rid)
    else:
        seeds = set(relevant_rule_ids)
    if not seeds:
        return set(relevant_rule_ids)

    # Rules that can reach an anchor in execution flow (producer -> ... -> anchor).
    # Given edges consumer -> producer in dep_graph.dependencies, this is the
    # reverse closure from anchors via dependencies.
    ancestors_of_anchors: set[RuleId] = set()
    stack = list(anchors)
    while stack:
        rid = stack.pop()
        if rid in ancestors_of_anchors:
            continue
        ancestors_of_anchors.add(rid)
        for dep in dep_graph.dependencies.get(rid, frozenset()):
            if dep in relevant_rule_ids and dep not in ancestors_of_anchors:
                stack.append(dep)

    # Rules reachable from seeds in execution flow via dependents.
    descendants_of_seeds: set[RuleId] = set()
    stack = list(seeds)
    while stack:
        rid = stack.pop()
        if rid in descendants_of_seeds:
            continue
        descendants_of_seeds.add(rid)
        for nxt in dep_graph.dependents.get(rid, frozenset()):
            if nxt in relevant_rule_ids and nxt not in descendants_of_seeds:
                stack.append(nxt)

    path_rules = relevant_rule_ids & ancestors_of_anchors & descendants_of_seeds
    return path_rules if path_rules else set(relevant_rule_ids)


def _compute_rule_dependencies_trace_attr_aware(
    transformation: Transformation,
    property: Property,
) -> RuleDependencyGraph:
    """
    Trace-aware dependency graph refined with:
    - local guard/where satisfiability pruning,
    - property-compatibility pruning,
    - attribute-flow preference (fallback-preserving).
    """
    dependencies: dict[RuleId, set[RuleId]] = {}
    dependents: dict[RuleId, set[RuleId]] = {}
    rule_layer: dict[RuleId, int] = {}

    prop_attr = _property_attr_summary(property)
    prop_keys = prop_attr.touched
    rule_by_id = {r.id: r for r in transformation.all_rules}
    rule_attr = {rid: _rule_attr_summary(r) for rid, r in rule_by_id.items()}

    trace_producers: dict[tuple[ClassId, ClassId], set[RuleId]] = {}
    type_producers: dict[ClassId, set[RuleId]] = {}

    for layer_idx, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            rule_layer[rule.id] = layer_idx
            dependencies[rule.id] = set()
            dependents[rule.id] = set()

            # Dead rule by local contradictions: skip as producer.
            if rule_attr[rule.id].definitely_unsat():
                continue

            backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
            created_apply_types = {
                ae.class_type for ae in rule.apply_elements
                if ae.id not in backward_apply_ids
            }
            match_types = {me.class_type for me in rule.match_elements}
            for t in created_apply_types:
                type_producers.setdefault(t, set()).add(rule.id)
                for s in match_types:
                    trace_producers.setdefault((s, t), set()).add(rule.id)

    def _filter_candidates(
        consumer_id: RuleId,
        candidates: set[RuleId],
    ) -> set[RuleId]:
        if not candidates:
            return candidates
        # Compatible with property + consumer constraints
        compat = {
            rid for rid in candidates
            if _merge_constraint_compat(rule_attr[rid].constraints, prop_attr.constraints)
            and _merge_constraint_compat(rule_attr[rid].constraints, rule_attr[consumer_id].constraints)
        }
        if compat:
            candidates = compat

        # Attribute-flow preference:
        # prefer producers that either touch property attrs or share attrs with consumer.
        if candidates:
            consumer_touch = rule_attr[consumer_id].touched
            scored = []
            for rid in candidates:
                touch = rule_attr[rid].touched
                score = 0
                if prop_keys and (touch & prop_keys):
                    score += 2
                if touch & consumer_touch:
                    score += 1
                scored.append((score, rid))
            max_score = max((s for s, _ in scored), default=0)
            if max_score > 0:
                candidates = {rid for s, rid in scored if s == max_score}
        return candidates

    for layer_idx, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            if not rule.has_backward_links:
                continue
            if rule_attr[rule.id].definitely_unsat():
                continue
            for bl in rule.backward_links:
                apply_elem = rule.apply_element_by_id.get(bl.apply_element)
                match_elem = rule.match_element_by_id.get(bl.match_element)
                if apply_elem is None or match_elem is None:
                    continue
                required_t = apply_elem.class_type
                required_s = match_elem.class_type
                candidates = set(trace_producers.get((required_s, required_t), set()))
                filtered = _filter_candidates(rule.id, candidates)
                use = filtered if filtered else candidates
                for producer_id in use:
                    producer_layer = rule_layer.get(producer_id, 0)
                    if producer_layer < layer_idx:
                        dependencies[rule.id].add(producer_id)
                        dependents[producer_id].add(rule.id)

    return RuleDependencyGraph(
        dependencies={k: frozenset(v) for k, v in dependencies.items()},
        dependents={k: frozenset(v) for k, v in dependents.items()},
        rule_layer=rule_layer,
    )


@dataclass
class CutoffBoundDetails:
    """Detailed result of cutoff bound computation."""
    bound: int
    c: int
    m: int
    p: int
    d: int
    a: int
    r: int
    bound_coarse: int
    bound_sharp: int
    bound_sharp2: int = 0
    bound_tight: int = 0
    relevant_rule_ids: list[RuleId] = field(default_factory=list)
    relevant_class_names: list[str] = field(default_factory=list)


def build_fragment(transformation: Transformation, layer_indices: list[int]) -> Transformation:
    """
    Build a fragment transformation with only the given layers (by index).
    E.g. layer_indices=[0, 1, 2] for L1, L2, L3.
    """
    layers = tuple(transformation.layers[i] for i in sorted(set(layer_indices)) if 0 <= i < len(transformation.layers))
    if not layers:
        raise ValueError("Fragment must have at least one layer")
    return Transformation(
        name=transformation.name + "_frag",
        source_metamodel=transformation.source_metamodel,
        target_metamodel=transformation.target_metamodel,
        layers=layers,
    )


def _rule_to_layer_index(transformation: Transformation) -> dict[RuleId, int]:
    """Map each rule id to its layer index (0-based)."""
    result: dict[RuleId, int] = {}
    for i, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            result[rule.id] = i
    return result


def _minimal_satisfying_closure(
    transformation: Transformation,
    property: Property,
    type_producers: dict,
    pre_type_counts: Optional[dict[str, int]] = None,
) -> dict[RuleId, set[RuleId]]:
    """For each rule that produces a postcondition type, compute transitive dependency closure.

    Layer-aware: backward links in a rule at layer i can only reference elements
    created by rules in layers 0..i-1 (DSLTrans semantics). This prevents the
    closure from exploding by including rules from later layers.

    D3 behavior: for each backward-link requirement, select a predecessor layer
    via calibrated scoring, then include all producers from that selected layer
    rather than only one producer rule.
    """
    rule_to_layer = _rule_to_layer_index(transformation)
    post_types = {e.class_type for e in property.postcondition.elements}
    satisfying_rules = set()
    for tid in post_types:
        satisfying_rules.update(type_producers.get(tid, set()))

    pre_type_counts = pre_type_counts or {}

    def _rule_match_counts(rule: Rule) -> dict[str, int]:
        counts: dict[str, int] = {}
        for me in rule.match_elements:
            counts[me.class_type] = counts.get(me.class_type, 0) + 1
        return counts

    def _pre_alignment_score(rule_id: RuleId, current_layer: int) -> tuple[int, int, int]:
        """
        Higher is better:
        - maximize overlap with property precondition element types,
        - minimize extra unmatched rule-match types,
        - prefer earlier predecessor layers for smaller fragments.
        """
        rule = next((r for ly in transformation.layers for r in ly.rules if r.id == rule_id), None)
        if rule is None:
            return (-1, -10_000, -10_000)
        match_counts = _rule_match_counts(rule)
        coverage = 0
        extra = 0
        for t, n in match_counts.items():
            pn = pre_type_counts.get(t, 0)
            coverage += min(n, pn)
            if n > pn:
                extra += (n - pn)
        layer_idx = rule_to_layer.get(rule_id, current_layer)
        return (coverage, -extra, -layer_idx)

    def closure(rule_id: RuleId, visited: set[RuleId] | None = None) -> set[RuleId]:
        visited = visited or set()
        if rule_id in visited:
            return set()
        visited.add(rule_id)
        out: set[RuleId] = {rule_id}
        rule = next(
            (r for layer in transformation.layers for r in layer.rules if r.id == rule_id),
            None,
        )
        if rule is None:
            return out
        rule_layer = rule_to_layer.get(rule_id, 0)
        for bl in rule.backward_links:
            ae = rule.apply_element_by_id.get(bl.apply_element)
            if ae is None:
                continue
            required_type = ae.class_type
            candidate_producers = [
                prod_id
                for prod_id in type_producers.get(required_type, set())
                # Only follow to rules in earlier layers (DSLTrans backward-link semantics)
                if rule_to_layer.get(prod_id, 0) < rule_layer
            ]
            if not candidate_producers:
                continue
            # Calibrated closure: pick the best predecessor layer by score, then
            # include all producers from that same layer. This avoids brittle
            # single-producer fragments while preserving layer-aware minimization.
            best_prod = max(
                candidate_producers,
                key=lambda rid: _pre_alignment_score(rid, rule_layer),
            )
            best_layer = rule_to_layer.get(best_prod, 0)
            selected_producers = sorted(
                prod_id
                for prod_id in candidate_producers
                if rule_to_layer.get(prod_id, 0) == best_layer
            )
            for prod_id in selected_producers:
                out.update(closure(prod_id, visited))
        return out

    return {rid: closure(rid) for rid in satisfying_rules}


def minimal_satisfying_layer_indices(
    transformation: Transformation,
    property: Property,
) -> list[int]:
    """
    Compute minimal layer indices for a sound fragment that can satisfy the property.
    Reusable for any DSLTrans transformation.

    Algorithm:
    1. Analyse postcondition trace links: each trace link (post_elem, pre_elem)
       requires a rule that matches the pre_elem's type AND produces the post_elem's
       type. This is the "satisfying rule" for that trace link.
    2. For post elements without trace links, any rule producing that type suffices.
    3. For each required rule, compute its transitive backward-link dependency closure.
    4. Fragment layers = {0} ∪ union of layers from all selected closures.
       Always includes layer 0 for soundness (backward links need earlier layers).

    This ensures every trace-linked (pre_type -> post_type) pair and every unlinked
    post_type has a producing rule in the fragment, which is required for soundness.

    Candidate selection uses a calibrated score (precondition type coverage, witness
    quality, and closure size) rather than closure size alone. This avoids selecting
    syntactically cheap but semantically weak witnesses (for example, a generic
    Class->Table rule for properties that require inheritance context).
    """
    post_types = {e.class_type for e in property.postcondition.elements}
    post_elem_by_id = {e.id: e for e in property.postcondition.elements}
    pre_elem_by_id = {}
    if property.precondition:
        pre_elem_by_id = {e.id: e for e in property.precondition.elements}

    type_producers: dict = {}
    link_producers: dict[tuple[str, ClassId, ClassId], set[RuleId]] = {}
    for layer in transformation.layers:
        for rule in layer.rules:
            backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
            for ae in rule.apply_elements:
                if ae.id in backward_apply_ids:
                    continue
                tid = ae.class_type
                if tid not in type_producers:
                    type_producers[tid] = set()
                type_producers[tid].add(rule.id)
            for al in rule.apply_links:
                src_elem = rule.apply_element_by_id.get(al.source)
                tgt_elem = rule.apply_element_by_id.get(al.target)
                if src_elem is None or tgt_elem is None:
                    continue
                key = (str(al.assoc_type), src_elem.class_type, tgt_elem.class_type)
                link_producers.setdefault(key, set()).add(rule.id)

    # Build index: (match_type, apply_type) -> set of rule ids
    match_apply_producers: dict[tuple, set[RuleId]] = {}
    for layer in transformation.layers:
        for rule in layer.rules:
            match_types = {me.class_type for me in rule.match_elements}
            backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
            apply_types = {
                ae.class_type for ae in rule.apply_elements
                if ae.id not in backward_apply_ids
            }
            for mt in match_types:
                for at in apply_types:
                    key = (mt, at)
                    if key not in match_apply_producers:
                        match_apply_producers[key] = set()
                    match_apply_producers[key].add(rule.id)

    rule_to_layer = _rule_to_layer_index(transformation)
    rule_by_id = {r.id: r for layer in transformation.layers for r in layer.rules}

    def layers_for_rules(rule_set: set[RuleId]) -> set[int]:
        indices: set[int] = set()
        for rid in rule_set:
            if rid in rule_to_layer:
                indices.add(rule_to_layer[rid])
        return indices

    def _count_types(elems) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in elems:
            counts[e.class_type] = counts.get(e.class_type, 0) + 1
        return counts

    pre_type_counts: dict[str, int] = {}
    if property.precondition:
        pre_type_counts = _count_types(property.precondition.elements)
    post_type_counts = _count_types(property.postcondition.elements)
    closures = _minimal_satisfying_closure(
        transformation,
        property,
        type_producers,
        pre_type_counts=pre_type_counts,
    )

    def _rule_match_counts(rule: Rule) -> dict[str, int]:
        return _count_types(rule.match_elements)

    def _rule_apply_type_set(rule: Rule) -> set[str]:
        backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
        return {
            ae.class_type for ae in rule.apply_elements
            if ae.id not in backward_apply_ids
        }

    def _rule_has_attr_constraints(rule: Rule) -> bool:
        if rule.guard is not None:
            return True
        return any(me.where_clause is not None for me in rule.match_elements)

    def _has_trace_typed_backward(rule: Rule, pre_type: str, post_type: str) -> bool:
        for bl in rule.backward_links:
            me = rule.match_element_by_id.get(bl.match_element)
            ae = rule.apply_element_by_id.get(bl.apply_element)
            if me is None or ae is None:
                continue
            if me.class_type == pre_type and ae.class_type == post_type:
                return True
        return False

    def _candidate_score(
        rid: RuleId,
        pre_type_for_trace: Optional[str] = None,
        post_type_for_trace: Optional[str] = None,
    ) -> tuple[int, int, int, int, int, int, int]:
        """
        Higher is better.
        Order of preference:
        1) typed trace witness (for trace-linked post elements),
        2) precondition type coverage (multiset),
        3) ability to produce more postcondition element types,
        4) fewer missing/extra precondition types,
        5) presence of guard/where constraints (more specific witness),
        6) smaller closure as a final tie-breaker.
        """
        rule = rule_by_id.get(rid)
        if rule is None:
            return (-1, -1, -1, -10_000, -10_000, -1, -10_000)

        match_counts = _rule_match_counts(rule)
        apply_types = _rule_apply_type_set(rule)
        closure_layers = layers_for_rules(closures[rid]) if rid in closures else {rule_to_layer.get(rid, 0)}

        coverage = 0
        missing = 0
        for t, n in pre_type_counts.items():
            rn = match_counts.get(t, 0)
            coverage += min(rn, n)
            if rn < n:
                missing += (n - rn)
        extra = 0
        for t, rn in match_counts.items():
            pn = pre_type_counts.get(t, 0)
            if rn > pn:
                extra += (rn - pn)

        post_cover = sum(min(post_type_counts.get(t, 0), 1) for t in apply_types)
        has_constraints = 1 if _rule_has_attr_constraints(rule) else 0
        typed_trace = 0
        if pre_type_for_trace is not None and post_type_for_trace is not None:
            typed_trace = 1 if _has_trace_typed_backward(rule, pre_type_for_trace, post_type_for_trace) else 0
        closure_cost = len(closure_layers)

        return (
            typed_trace,
            coverage,
            post_cover,
            -missing,
            -extra,
            has_constraints,
            -closure_cost,
        )

    def _pick_best_candidate(
        candidates: set[RuleId],
        pre_type_for_trace: Optional[str] = None,
        post_type_for_trace: Optional[str] = None,
    ) -> Optional[RuleId]:
        if not candidates:
            return None
        best_rid: Optional[RuleId] = None
        best_score: Optional[tuple[int, int, int, int, int, int, int]] = None
        for rid in candidates:
            score = _candidate_score(rid, pre_type_for_trace, post_type_for_trace)
            if best_score is None or score > best_score:
                best_rid = rid
                best_score = score
        return best_rid

    # Determine required rules from trace links
    required_rules: set[RuleId] = set()
    covered_post_ids: set = set()
    trace_links = getattr(property.postcondition, 'trace_links', ()) or ()
    for post_id, pre_id in trace_links:
        post_elem = post_elem_by_id.get(post_id)
        pre_elem = pre_elem_by_id.get(pre_id)
        if not post_elem or not pre_elem:
            continue
        covered_post_ids.add(post_id)
        key = (pre_elem.class_type, post_elem.class_type)
        candidates = match_apply_producers.get(key, set())
        best_rid = _pick_best_candidate(
            candidates,
            pre_type_for_trace=pre_elem.class_type,
            post_type_for_trace=post_elem.class_type,
        )
        if best_rid is not None:
            required_rules.add(best_rid)

    # For post elements without trace links, prefer rules that match a precondition
    # type AND produce the postcondition type. This ensures the fragment includes
    # rules that fire when the precondition pattern is present.
    pre_types = set()
    if property.precondition:
        pre_types = {e.class_type for e in property.precondition.elements}

    # Prefer a single rule that produces ALL postcondition types and matches only
    # precondition types (so it can fire when the precondition holds). This avoids
    # spurious counterexamples when the postcondition has multiple elements from
    # one rule (e.g. Generalization2Extends produces both ClassDeclaration and TypeReference).
    post_type_set = post_types
    full_cover_rules: set[RuleId] = set()
    for layer in transformation.layers:
        for rule in layer.rules:
            backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
            rule_apply_types = {
                ae.class_type for ae in rule.apply_elements
                if ae.id not in backward_apply_ids
            }
            rule_match_types = {me.class_type for me in rule.match_elements}
            # Rule must produce all post types and match only pre types (subset),
            # so it can fire on the precondition pattern.
            if (
                post_type_set.issubset(rule_apply_types)
                and pre_types
                and rule_match_types.issubset(pre_types)
            ):
                full_cover_rules.add(rule.id)
    if full_cover_rules:
        best_rid = _pick_best_candidate(full_cover_rules)
        if best_rid is not None:
            required_rules.add(best_rid)

    for elem in property.postcondition.elements:
        if elem.id in covered_post_ids:
            continue
        # First try: rules matching a pre type AND producing this post type
        candidates = set()
        for pt in pre_types:
            candidates.update(match_apply_producers.get((pt, elem.class_type), set()))
        if not candidates:
            # Fallback: any rule producing this type
            candidates = type_producers.get(elem.class_type, set())
        best_rid = _pick_best_candidate(candidates)
        if best_rid is not None:
            required_rules.add(best_rid)

    for link in property.postcondition.links:
        src_elem = post_elem_by_id.get(link.source)
        tgt_elem = post_elem_by_id.get(link.target)
        if src_elem is None or tgt_elem is None:
            continue
        candidates = link_producers.get(
            (str(link.assoc_type), src_elem.class_type, tgt_elem.class_type),
            set(),
        )
        best_rid = _pick_best_candidate(candidates)
        if best_rid is not None:
            required_rules.add(best_rid)

    # Collect all layers from closures of required rules
    selected_layers: set[int] = {0}
    for rid in required_rules:
        if rid in closures:
            selected_layers.update(layers_for_rules(closures[rid]))
        elif rid in rule_to_layer:
            selected_layers.add(rule_to_layer[rid])

    if not selected_layers:
        return [0] if transformation.layers else []
    return sorted(selected_layers)


def layer_indices_for_rules(transformation: Transformation, rule_ids: set[RuleId]) -> list[int]:
    """
    Return sorted layer indices for a *sound* minimal fragment.

    - Includes every layer that contains at least one of the given rules.
    - Always includes layer 0 when any layer > 0 is included, so rules in later
      layers that have backward links have an earlier layer to create traces
      (otherwise they would never fire and the fragment would be unsound).

    Used to build a minimal fragment for verification (monotonicity: HOLDS for
    fragment => HOLDS for full transformation).
    """
    indices: set[int] = set()
    for i, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            if rule.id in rule_ids:
                indices.add(i)
                break
    # Sound fragment: if we include any later layer, include layer 0 for backward-link rules.
    if indices and 0 not in indices and any(i > 0 for i in indices):
        indices.add(0)
    return sorted(indices)


def get_relevant_rules(transformation: Transformation, property: Property) -> set[RuleId]:
    """
    Return the set of rule IDs that can contribute to the property.

    Computed on each call (no caching). Algorithm: start from rules that produce
    the property's postcondition types; add all rules that produce types required
    by backward links; repeat until fixed point. Used for property-directed
    slicing and for building minimal fragments.
    """
    return _relevant_rules(transformation, property)


def compute_per_class_slot_bounds_fixed_point(
    transformation: Transformation,
    property: Property,
    relevant_rule_ids: set[RuleId],
    global_bound: int,
    relevant_src_classes: Optional[set[str]] = None,
    relevant_tgt_classes: Optional[set[str]] = None,
) -> tuple[dict[str, int], dict[str, int]]:
    """
    Compute theorem-aligned per-class slot bounds.

    The fixed-point follows the strengthened cutoff theory:
    - source seed counts from the property precondition,
    - mandatory source-side closure,
    - target production counts from relevant rule firings,
    - mandatory target-side closure,
    - global cap by ``global_bound``.

    The encoding keeps a minimum matrix dimension of one slot per retained
    class, but unused slots may be marked non-existent by the SMT model.
    """
    src_map = {str(c.id): c.name for c in transformation.source_metamodel.classes}
    src_map.update({c.name: c.name for c in transformation.source_metamodel.classes})
    tgt_map = {str(c.id): c.name for c in transformation.target_metamodel.classes}
    tgt_map.update({c.name: c.name for c in transformation.target_metamodel.classes})

    src_classes = {
        c.name for c in transformation.source_metamodel.classes
        if relevant_src_classes is None or c.name in relevant_src_classes
    }
    tgt_classes = {
        c.name for c in transformation.target_metamodel.classes
        if relevant_tgt_classes is None or c.name in relevant_tgt_classes
    }
    src_bounds: dict[str, int] = {c: 1 for c in src_classes}
    # Target bounds start at the encoding floor (one optional slot per retained
    # class), then grow according to theorem-aligned target production and
    # mandatory target closure.
    tgt_bounds: dict[str, int] = {c: 1 for c in tgt_classes}
    
    def _cap(v: int) -> int:
        return max(1, min(global_bound, int(v)))

    def _bump(bounds: dict[str, int], cls_name: str, val: int) -> bool:
        if cls_name not in bounds:
            return False
        new_v = _cap(val)
        if new_v > bounds[cls_name]:
            bounds[cls_name] = new_v
            return True
        return False

    def _count_classes(elements, name_map: dict[str, str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in elements:
            cls_name = name_map.get(str(e.class_type), str(e.class_type))
            out[cls_name] = out.get(cls_name, 0) + 1
        return out

    rule_by_id = {r.id: r for r in transformation.all_rules}
    relevant_rules = [rule_by_id[rid] for rid in relevant_rule_ids if rid in rule_by_id]

    def _bump(bounds: dict[str, int], cls_name: str, val: int) -> bool:
        if cls_name not in bounds:
            return False
        new_v = _cap(val)
        if new_v > bounds[cls_name]:
            bounds[cls_name] = new_v
            return True
        return False

    def _count_classes(elements, name_map: dict[str, str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in elements:
            cls_name = name_map.get(str(e.class_type), str(e.class_type))
            out[cls_name] = out.get(cls_name, 0) + 1
        return out

    rule_by_id = {r.id: r for r in transformation.all_rules}
    relevant_rules = [rule_by_id[rid] for rid in relevant_rule_ids if rid in rule_by_id]

    # Source seed sufficiency from the theory: the base source witness is the
    # property precondition, then source mandatory closure expands it only as
    # needed for well-formedness.
    pre_counts = (
        _count_classes(property.precondition.elements, src_map)
        if property.precondition is not None
        else {}
    )

    for cls_name in list(src_bounds.keys()):
        p_c = pre_counts.get(cls_name, 0)
        base = p_c
        _bump(src_bounds, cls_name, base)

    # Multiplicity constraints from source metamodel (mirrors encoder semantics)
    source_assoc_constraints: list[tuple[str, str, tuple[int, Optional[int]], tuple[int, Optional[int]], bool]] = []
    for assoc in transformation.source_metamodel.associations:
        src_cls = src_map.get(str(assoc.source_class))
        tgt_cls = src_map.get(str(assoc.target_class))
        if not src_cls or not tgt_cls:
            continue
        if src_cls not in src_bounds or tgt_cls not in src_bounds:
            continue
        source_assoc_constraints.append(
            (src_cls, tgt_cls, assoc.source_mult, assoc.target_mult, bool(assoc.is_containment))
        )

    # Monotone fixed-point
    changed = True
    max_iters = max(4, 2 * len(src_bounds))
    iters = 0
    while changed and iters < max_iters:
        iters += 1
        changed = False

    # Source mandatory closure (fixed-point scaling):
        # - if target end is mandatory (target_mult min>=1):
        #   each source instance needs target_mult_min targets
        #   => K_tgt >= ceil((K_src * target_mult_min) / source_mult_max)
        # - if source end is mandatory (source_mult min>=1):
        #   each target instance needs source_mult_min sources
        #   => K_src >= ceil((K_tgt * source_mult_min) / target_mult_max)
        for src_cls, tgt_cls, src_mult, tgt_mult, is_containment in source_assoc_constraints:
            src_min, src_max = src_mult
            tgt_min, tgt_max = tgt_mult
            
            if tgt_min >= 1 and src_bounds.get(src_cls, 0) > 0:
                if src_max is None or src_max == -1:
                    req_tgt = tgt_min
                else:
                    req_tgt = (src_bounds[src_cls] * tgt_min + src_max - 1) // src_max
                changed |= _bump(src_bounds, tgt_cls, req_tgt)
                
            if src_min >= 1 and src_bounds.get(tgt_cls, 0) > 0:
                if tgt_max is None or tgt_max == -1:
                    req_src = src_min
                else:
                    req_src = (src_bounds[tgt_cls] * src_min + tgt_max - 1) // tgt_max
                changed |= _bump(src_bounds, src_cls, req_src)

    # Target production bound:
    #   K_tgt(C) = p_C + sum_R (max_firings(R) * apply_count_R(C))
    # where max_firings(R) is conservatively bounded by the product of source
    # bounds for the rule's match element classes.
    tgt_bounds: dict[str, int] = {c: 1 for c in tgt_classes}
    
    post_counts = _count_classes(property.postcondition.elements, tgt_map)
    rule_max_firings: dict[RuleId, int] = {}
    rule_apply_counts: dict[RuleId, dict[str, int]] = {}
    for rule in relevant_rules:
        firings = 1
        for me in rule.match_elements:
            c_name = src_map.get(str(me.class_type), str(me.class_type))
            firings *= src_bounds.get(c_name, 1)
        rule_max_firings[rule.id] = firings
        rule_apply_counts[rule.id] = _count_classes(rule.apply_elements, tgt_map)

    for cls_name in list(tgt_bounds.keys()):
        p_c = post_counts.get(cls_name, 0)
        total_from_rules = 0
        for rule in relevant_rules:
            apply_n = rule_apply_counts.get(rule.id, {}).get(cls_name, 0)
            if apply_n > 0:
                total_from_rules += rule_max_firings.get(rule.id, 0) * apply_n

        base = p_c + total_from_rules
        _bump(tgt_bounds, cls_name, base)

    # Target mandatory closure (fixed-point scaling)
    target_assoc_constraints: list[tuple[str, str, tuple[int, Optional[int]], tuple[int, Optional[int]], bool]] = []
    for assoc in transformation.target_metamodel.associations:
        src_cls = tgt_map.get(str(assoc.source_class))
        tgt_cls = tgt_map.get(str(assoc.target_class))
        if not src_cls or not tgt_cls:
            continue
        if src_cls not in tgt_bounds or tgt_cls not in tgt_bounds:
            continue
        target_assoc_constraints.append(
            (src_cls, tgt_cls, assoc.source_mult, assoc.target_mult, bool(assoc.is_containment))
        )

    changed = True
    iters = 0
    while changed and iters < max_iters:
        iters += 1
        changed = False

        for src_cls, tgt_cls, src_mult, tgt_mult, is_containment in target_assoc_constraints:
            src_min, src_max = src_mult
            tgt_min, tgt_max = tgt_mult
            
            if tgt_min >= 1 and tgt_bounds.get(src_cls, 0) > 0:
                if src_max is None or src_max == -1:
                    req_tgt = tgt_min
                else:
                    req_tgt = (tgt_bounds[src_cls] * tgt_min + src_max - 1) // src_max
                changed |= _bump(tgt_bounds, tgt_cls, req_tgt)
                
            if src_min >= 1 and tgt_bounds.get(tgt_cls, 0) > 0:
                if tgt_max is None or tgt_max == -1:
                    req_src = src_min
                else:
                    req_src = (tgt_bounds[tgt_cls] * src_min + tgt_max - 1) // tgt_max
                changed |= _bump(tgt_bounds, src_cls, req_src)

    return src_bounds, tgt_bounds


def compute_dependency_graph(
    transformation: Transformation,
    property: Optional[Property] = None,
    dependency_mode: str = "legacy",
) -> RuleDependencyGraph:
    """Compute rule dependency graph for the selected mode.

    For ``trace_attr_aware`` mode, ``property`` is required because
    compatibility pruning depends on property-side attribute constraints.
    """
    if dependency_mode == "legacy":
        return compute_rule_dependencies(transformation)
    if dependency_mode == "trace_aware":
        return compute_rule_dependencies_trace_aware(transformation)
    if dependency_mode == "trace_attr_aware":
        if property is None:
            raise ValueError("property is required for dependency_mode='trace_attr_aware'")
        return _compute_rule_dependencies_trace_attr_aware(transformation, property)
    raise ValueError(f"Unknown dependency_mode: {dependency_mode}")


def compute_cutoff_bound(
    transformation: Transformation,
    property: Property,
    use_reduced_k: bool = True,
    dependency_mode: str = "legacy",
    dependency_graph: Optional[RuleDependencyGraph] = None,
    ignore_containment_for_arity: bool = False,
    use_path_aware_depth: bool = False,
) -> int:
    """
    Compute property-specific cutoff K.

    When use_reduced_k=True (default): K = min(coarse, sharp, sharp2, tight) for smaller
    bounds. When use_reduced_k=False: K = bound_coarse (Theorem 4.9) for
    conservative soundness checks.

    `use_path_aware_depth=True` enables a property-path-aware depth heuristic for `d`
    (precondition-seed -> postcondition-anchor dependency paths). Keep this disabled
    for strict theorem-style cutoff calculations.
    """
    details = compute_cutoff_bound_detailed(
        transformation,
        property,
        use_reduced_k=use_reduced_k,
        dependency_mode=dependency_mode,
        dependency_graph=dependency_graph,
        ignore_containment_for_arity=ignore_containment_for_arity,
        use_path_aware_depth=use_path_aware_depth,
    )
    return details.bound


def compute_cutoff_bound_detailed(
    transformation: Transformation,
    property: Property,
    use_reduced_k: bool = True,
    dependency_mode: str = "legacy",
    dependency_graph: Optional[RuleDependencyGraph] = None,
    ignore_containment_for_arity: bool = False,
    use_path_aware_depth: bool = False,
) -> CutoffBoundDetails:
    """
    Compute cutoff bound with full breakdown.

    - Relevant rules: backward from postcondition types.
    - Relevant classes: property pre/post types + match/apply types of relevant rules.
    - d: depth of dependency subgraph on relevant rules.
    - use_reduced_k: if True, bound = min(coarse, sharp, sharp2, tight); if False, bound = coarse.
    - use_path_aware_depth: if True, compute d on a property-path-aware subset of
      relevant rules (heuristic). Disable for strict theorem-style cutoff.
    """
    if dependency_mode not in ("legacy", "trace_aware", "trace_attr_aware"):
        raise ValueError(f"Unknown dependency_mode: {dependency_mode}")

    if dependency_mode == "legacy":
        relevant = _relevant_rules(transformation, property)
    elif dependency_mode == "trace_aware":
        relevant = _relevant_rules_trace_aware(transformation, property)
    else:
        relevant = _relevant_rules_trace_attr_aware(transformation, property)
    all_rules = transformation.all_rules
    relevant_rules_list = [r for r in all_rules if r.id in relevant]

    # Relevant classes
    class_ids: set = set()
    if property.precondition:
        for e in property.precondition.elements:
            class_ids.add(e.class_type)
    for e in property.postcondition.elements:
        class_ids.add(e.class_type)
    for rule in relevant_rules_list:
        for me in rule.match_elements:
            class_ids.add(me.class_type)
        for ae in rule.apply_elements:
            class_ids.add(ae.class_type)
    # ClassId may be string; we need count of distinct source metamodel classes that appear
    source_class_ids = {c.id for c in transformation.source_metamodel.classes}
    c = len(class_ids & source_class_ids) if source_class_ids else len(class_ids)
    if c == 0:
        c = 1
    relevant_class_names = sorted(str(x) for x in class_ids)

    m = max((len(r.match_elements) for r in relevant_rules_list), default=0)
    pre_size = len(property.precondition.elements) if property.precondition else 0
    post_size = len(property.postcondition.elements)
    p = max(pre_size, post_size)

    if dependency_graph is not None:
        dep_graph = dependency_graph
    elif dependency_mode == "legacy":
        dep_graph = compute_rule_dependencies(transformation)
    elif dependency_mode == "trace_aware":
        dep_graph = compute_rule_dependencies_trace_aware(transformation)
    else:
        dep_graph = _compute_rule_dependencies_trace_attr_aware(transformation, property)
    depth_rule_ids = relevant
    if use_path_aware_depth:
        depth_rule_ids = _path_aware_rules_for_depth(
            transformation,
            property,
            dep_graph,
            relevant,
        )
    d = _dependency_depth(dep_graph, depth_rule_ids)
    d = max(d, 1)

    a = _association_arity(
        transformation.source_metamodel, class_ids,
        match_arity_bound=max(m, 1),
        ignore_containment=ignore_containment_for_arity,
    )

    r = len(relevant_rules_list)

    # --- Three cutoff bounds, take the minimum ---
    # Coarse bound (Theorem 4.9): conservative, uses class count c
    bound_coarse = c * (m + p) * d * (a + 1)
    # Sharp bound (Theorem 4.10): uses relevant rule count r
    bound_sharp = p * (1 + m * r) * d * (a + 1)
    # Sharp2 bound (D11): tighter than bound_sharp when d > 1
    # by distributing d only over the m*r term.
    bound_sharp2 = p * (1 + m * r * d) * (a + 1)
    # Tight bound (direct counting, Corollary 4.12): uses layered structure
    # Over d layers, at most r rules fire per support element, each adding
    # at most m-1 new elements.  Total support ≤ p·(1 + (m-1)·r·d).
    bound_tight = p * (1 + (m - 1) * r * d) * (a + 1)
    if use_reduced_k:
        K = min(bound_coarse, bound_sharp, bound_sharp2, bound_tight)
    else:
        K = bound_coarse
    K = max(K, 1)

    return CutoffBoundDetails(
        bound=K,
        c=c,
        m=m,
        p=p,
        d=d,
        a=a,
        r=r,
        bound_coarse=bound_coarse,
        bound_sharp=bound_sharp,
        bound_sharp2=bound_sharp2,
        bound_tight=bound_tight,
        relevant_rule_ids=sorted(relevant),
        relevant_class_names=relevant_class_names,
    )


def _association_arity(
    metamodel: Metamodel,
    relevant_classes: set,
    match_arity_bound: int = 1,
    ignore_containment: bool = False,
) -> int:
    """
    Compute effective association arity for closure as transitive mandatory reachability.

    We build a directed graph on source classes where an edge A -> B exists if
    a mandatory multiplicity requires B when A is present (target min >= 1), and
    vice versa for mandatory source-side multiplicities. Then, for each relevant
    class, we count how many distinct classes are reachable via this transitive
    closure. The arity proxy `a` is the maximum such reachable count.
    """
    relevant = {str(c) for c in relevant_classes}
    adjacency: dict[str, set[str]] = {}
    for cls in metamodel.classes:
        adjacency[str(cls.id)] = set()

    for assoc in metamodel.associations:
        if ignore_containment and assoc.is_containment:
            continue
        src = str(assoc.source_class)
        tgt = str(assoc.target_class)
        if assoc.target_mult[0] >= 1:
            adjacency.setdefault(src, set()).add(tgt)
        if assoc.source_mult[0] >= 1:
            adjacency.setdefault(tgt, set()).add(src)

    def _reachable_count(start: str) -> int:
        seen: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            for nxt in adjacency.get(cur, set()):
                if nxt not in seen and nxt != start:
                    seen.add(nxt)
                    stack.append(nxt)
        return len(seen)

    a = 0
    for cls in relevant:
        a = max(a, _reachable_count(cls))
    return a if a > 0 else 1
