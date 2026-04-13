"""
SMT-Based Direct Verification for DSLTrans

Encodes the entire transformation semantics + property as a single SMT formula
for direct verification, bypassing explicit path condition enumeration.

Key insight:
  Instead of enumerating O(2^n) path conditions and checking each with SMT,
  we encode all possible executions in one SMT query. Z3 internally explores
  the non-deterministic choices when searching for counterexamples.

Rule Firing Semantics (4 Cases):
  Case 1: No backward links -> MAY fire (implication encoding)
  Case 2: Backward links, no matches -> CANNOT fire
  Case 3: Partial deps OR attr constraints -> MAY fire at each location (2^N branches)
  Case 4: Total deps, no attr constraints -> MUST fire at all locations (equivalence)

Attribute Constraints:
  Handled lazily - accumulated into Θ_attr and checked at property verification time.

See: dsltrans.tex "Direct SMT Verification" section.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from typing import Optional, Dict, List, Set, Tuple, FrozenSet
from enum import Enum
from itertools import product
import subprocess
import tempfile
import time
import z3

from .model import (
    Transformation, Property, Rule, RuleId, Layer, LayerId,
    MatchElement, ApplyElement, MatchLink, ApplyLink, BackwardLink,
    ClassId, ElementId, AssocId, MatchType, LinkKind,
    Metamodel, Class, Association, Attribute,
    Expr, IntLit, BoolLit, StringLit, ListLit, PairLit, VarRef, AttrRef, BinOp, UnaryOp, FuncCall,
    AttrType,
    PreCondition, PostCondition,
)
from .parser import ParsedSpec
from .cutoff import (
    check_fragment,
    compute_cutoff_bound,
    get_relevant_rules,
    _relevant_rules_trace_aware,
    _relevant_rules_trace_attr_aware,
    compute_per_class_slot_bounds_fixed_point,
)
from .cutoff import (
    _property_attr_summary,
    _rule_attr_summary,
    _merge_constraint_compat,
)
from .inheritance_flattening import (
    flatten_spec_for_property,
    lift_counterexample,
)


class CheckResult(Enum):
    """Result of incremental SMT checking."""
    HOLDS = "holds"           # Property verified to hold
    VIOLATED = "violated"     # Counterexample found
    UNKNOWN = "unknown"       # Timeout or resource limit


class ExprToZ3:
    """
    Translates DSLTrans attribute expressions to Z3 expressions.
    
    Handles algebraic data types: Int, Bool, String, List, Pair
    """
    
    def __init__(self, env: dict[str, z3.ExprRef] | None = None):
        """
        Args:
            env: Environment mapping variable names to Z3 expressions.
                 For attribute references like "e.age", the key is "e.age".
        """
        self.env = env or {}
        self._fresh_counter = 0
    
    def translate(self, expr: Expr) -> z3.ExprRef:
        """Translate a DSLTrans expression to Z3."""
        match expr:
            case IntLit(value=v):
                return z3.IntVal(v)
            
            case BoolLit(value=v):
                return z3.BoolVal(v)
            
            case StringLit(value=v):
                return z3.StringVal(v)
            
            case ListLit(elements=elems):
                if not elems:
                    # Empty list
                    return z3.Empty(z3.SeqSort(z3.IntSort()))
                # Build list by concatenation
                z3_elems = [self.translate(e) for e in elems]
                result = z3.Unit(z3_elems[0])
                for e in z3_elems[1:]:
                    result = z3.Concat(result, z3.Unit(e))
                return result
            
            case PairLit(fst=f, snd=s):
                # Fail closed until tuple datatype encoding is implemented.
                # Returning fst only was unsound and could mask violations.
                raise ValueError("Pair literal encoding is not supported in SMT checker")
            
            case VarRef(name=n):
                if n in self.env:
                    return self.env[n]
                # Create fresh variable if not found
                var = z3.Int(n)
                self.env[n] = var
                return var
            
            case AttrRef(element=elem, attribute=attr):
                key = f"{elem}.{attr}"
                if key in self.env:
                    return self.env[key]
                # Create fresh variable
                var = z3.Int(key)
                self.env[key] = var
                return var
            
            case BinOp(op=op, left=l, right=r):
                lz3 = self.translate(l)
                rz3 = self.translate(r)
                return self._translate_binop(op, lz3, rz3)
            
            case UnaryOp(op=op, operand=operand):
                oz3 = self.translate(operand)
                return self._translate_unaryop(op, oz3)
            
            case FuncCall(name=name, args=args):
                z3_args = [self.translate(a) for a in args]
                return self._translate_funcall(name, z3_args)
            
            case _:
                raise ValueError(f"Unknown expression type: {type(expr)}")
    
    def _translate_binop(self, op: str, left: z3.ExprRef, right: z3.ExprRef) -> z3.ExprRef:
        """Translate binary operation."""
        match op:
            # Arithmetic
            case "+":
                return left + right
            case "-":
                return left - right
            case "*":
                return left * right
            case "/":
                return left / right
            case "%":
                return left % right
            
            # Comparison
            case "==":
                return left == right
            case "!=":
                return left != right
            case "<":
                return left < right
            case "<=":
                return left <= right
            case ">":
                return left > right
            case ">=":
                return left >= right
            
            # Logical
            case "&&":
                return z3.And(left, right)
            case "||":
                return z3.Or(left, right)
            
            case _:
                raise ValueError(f"Unknown binary operator: {op}")
    
    def _translate_unaryop(self, op: str, operand: z3.ExprRef) -> z3.ExprRef:
        """Translate unary operation."""
        match op:
            case "!":
                return z3.Not(operand)
            case "-":
                return -operand
            case _:
                raise ValueError(f"Unknown unary operator: {op}")
    
    def _translate_funcall(self, name: str, args: list[z3.ExprRef]) -> z3.ExprRef:
        """Translate function call."""
        match name:
            # List operations
            case "head":
                if len(args) != 1:
                    raise ValueError("head requires 1 argument")
                return z3.Select(args[0], z3.IntVal(0))
            
            case "tail":
                if len(args) != 1:
                    raise ValueError("tail requires 1 argument")
                return z3.SubSeq(args[0], z3.IntVal(1), z3.Length(args[0]) - 1)
            
            case "append":
                if len(args) != 2:
                    raise ValueError("append requires 2 arguments")
                return z3.Concat(args[0], z3.Unit(args[1]))
            
            case "length":
                if len(args) != 1:
                    raise ValueError("length requires 1 argument")
                return z3.Length(args[0])
            
            case "isEmpty":
                if len(args) != 1:
                    raise ValueError("isEmpty requires 1 argument")
                return z3.Length(args[0]) == 0
            
            # String operations
            case "concat":
                if len(args) < 2:
                    raise ValueError("concat requires at least 2 arguments")
                result = args[0]
                for arg in args[1:]:
                    result = z3.Concat(result, arg)
                return result
            
            # Pair operations
            case "fst":
                if len(args) != 1:
                    raise ValueError("fst requires 1 argument")
                raise ValueError("fst() requires pair encoding support, currently unsupported")
            
            case "snd":
                if len(args) != 1:
                    raise ValueError("snd requires 1 argument")
                raise ValueError("snd() requires pair encoding support, currently unsupported")
            
            case _:
                raise ValueError(f"Unknown function: {name}")


def expr_to_z3(expr: Expr, env: dict[str, z3.ExprRef] | None = None) -> z3.ExprRef:
    """Convenience function to translate expression to Z3."""
    translator = ExprToZ3(env)
    return translator.translate(expr)


def _binding_injective_per_type(elements, binding, get_class_name) -> bool:
    """
    True iff binding assigns distinct indices to elements of the same type.
    Elements of different types may share an index (indices are per-type slots).
    """
    n = len(elements)
    if n != len(binding):
        return False
    for i in range(n):
        name_i = get_class_name(elements[i].class_type)
        for j in range(i + 1, n):
            if get_class_name(elements[j].class_type) != name_i:
                continue
            if binding[i] == binding[j]:
                return False
    return True


# -----------------------------------------------------------------------------
# Metamodel Slicing Helper
# -----------------------------------------------------------------------------

def compute_metamodel_slice(
    transformation: Transformation,
    prop: Property,
    relevant_rules: Set[RuleId],
) -> tuple[Set[str], Set[str], Set[str], Set[str]]:
    """Compute the minimal set of classes and associations needed for encoding.

    Starts from classes/associations directly referenced by *relevant_rules* and
    *prop*, then expands with a well-formedness closure: for every included source
    class, if any association has that class as an endpoint with mandatory
    multiplicity (≥ 1), include that association and the other endpoint.

    Returns (src_classes, tgt_classes, src_assocs, tgt_assocs).
    """
    src_mm = transformation.source_metamodel
    tgt_mm = transformation.target_metamodel

    src_cls: Set[str] = set()
    tgt_cls: Set[str] = set()
    src_assoc: Set[str] = set()
    tgt_assoc: Set[str] = set()

    # 1. Collect directly referenced classes/assocs from relevant rules
    for rule in transformation.all_rules:
        if rule.id not in relevant_rules:
            continue
        for me in rule.match_elements:
            src_cls.add(str(me.class_type))
        for ae in rule.apply_elements:
            tgt_cls.add(str(ae.class_type))
        for ml in rule.match_links:
            src_assoc.add(str(ml.assoc_type))
        for al in rule.apply_links:
            tgt_assoc.add(str(al.assoc_type))

    # 2. Collect from property pre/postcondition
    if prop.precondition:
        for e in prop.precondition.elements:
            src_cls.add(str(e.class_type))
        for l in prop.precondition.links:
            src_assoc.add(str(l.assoc_type))
    for e in prop.postcondition.elements:
        tgt_cls.add(str(e.class_type))
    for l in prop.postcondition.links:
        tgt_assoc.add(str(l.assoc_type))

    # 3. Well-formedness closure on source metamodel: for every included class,
    #    add associations where it must participate (mandatory multiplicity),
    #    and the class on the other end.  Iterate until fixed-point.
    _class_name_cache: dict[str, str] = {}
    for c in src_mm.classes:
        _class_name_cache[str(c.id)] = c.name
        _class_name_cache[c.name] = c.name

    changed = True
    while changed:
        changed = False
        for assoc in src_mm.associations:
            a_src = _class_name_cache.get(str(assoc.source_class))
            a_tgt = _class_name_cache.get(str(assoc.target_class))
            if not a_src or not a_tgt:
                continue
            # If target class is relevant and source_mult[0] >= 1 (target must
            # participate), pull in the association and the source class.
            if a_tgt in src_cls and assoc.source_mult[0] >= 1:
                if assoc.name not in src_assoc:
                    src_assoc.add(assoc.name)
                    changed = True
                if a_src not in src_cls:
                    src_cls.add(a_src)
                    changed = True
            # If source class is relevant and target_mult[0] >= 1 (source must
            # have >= 1 target), pull in the association and the target class.
            if a_src in src_cls and assoc.target_mult[0] >= 1:
                if assoc.name not in src_assoc:
                    src_assoc.add(assoc.name)
                    changed = True
                if a_tgt not in src_cls:
                    src_cls.add(a_tgt)
                    changed = True

    return src_cls, tgt_cls, src_assoc, tgt_assoc


def _iter_expr_nodes(expr: Expr):
    """Yield expression nodes in DFS order."""
    stack = [expr]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, BinOp):
            stack.append(cur.right)
            stack.append(cur.left)
        elif isinstance(cur, UnaryOp):
            stack.append(cur.operand)
        elif isinstance(cur, FuncCall):
            for a in reversed(cur.args):
                stack.append(a)


def _collect_used_string_attrs_for_property(
    transformation: Transformation,
    prop: Property,
    relevant_rules: Optional[Set[RuleId]],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """
    Collect (class_name, attr_name) pairs that are read/written by rule/property constraints.

    This is conservative: any attribute that appears in a where/guard/apply binding
    expression or apply-binding target is marked as used.
    """
    src_class_names = {c.name for c in transformation.source_metamodel.classes}
    tgt_class_names = {c.name for c in transformation.target_metamodel.classes}

    used_src: set[tuple[str, str]] = set()
    used_tgt: set[tuple[str, str]] = set()

    def mark_attr(elem_to_cls: dict[str, str], elem_name: str, attr_name: str) -> None:
        cls_name = elem_to_cls.get(elem_name)
        if not cls_name:
            return
        key = (cls_name, attr_name)
        if cls_name in src_class_names:
            used_src.add(key)
        elif cls_name in tgt_class_names:
            used_tgt.add(key)

    for layer in transformation.layers:
        for rule in layer.rules:
            if relevant_rules is not None and rule.id not in relevant_rules:
                continue
            elem_to_cls: dict[str, str] = {}
            for me in rule.match_elements:
                cls_name = str(me.class_type)
                elem_to_cls[me.name] = cls_name
                elem_to_cls[str(me.id)] = cls_name
            for ae in rule.apply_elements:
                cls_name = str(ae.class_type)
                elem_to_cls[ae.name] = cls_name
                elem_to_cls[str(ae.id)] = cls_name

            for me in rule.match_elements:
                if me.where_clause is None:
                    continue
                for node in _iter_expr_nodes(me.where_clause):
                    if isinstance(node, AttrRef):
                        mark_attr(elem_to_cls, node.element, node.attribute)
            if rule.guard is not None:
                for node in _iter_expr_nodes(rule.guard):
                    if isinstance(node, AttrRef):
                        mark_attr(elem_to_cls, node.element, node.attribute)

            for ae in rule.apply_elements:
                for b in ae.attribute_bindings:
                    # Target attribute is written.
                    mark_attr(elem_to_cls, b.target.element, b.target.attribute)
                    # Value expression may read source/target attributes.
                    for node in _iter_expr_nodes(b.value):
                        if isinstance(node, AttrRef):
                            mark_attr(elem_to_cls, node.element, node.attribute)

    pre = prop.precondition
    if pre:
        pre_elem_to_cls: dict[str, str] = {}
        for e in pre.elements:
            cls_name = str(e.class_type)
            pre_elem_to_cls[e.name] = cls_name
            pre_elem_to_cls[str(e.id)] = cls_name
        for e in pre.elements:
            if e.where_clause is None:
                continue
            for node in _iter_expr_nodes(e.where_clause):
                if isinstance(node, AttrRef):
                    mark_attr(pre_elem_to_cls, node.element, node.attribute)
    return used_src, used_tgt


def _reduce_unused_string_vocab_in_metamodel(
    mm: Metamodel,
    used_attrs: set[tuple[str, str]],
) -> Metamodel:
    """
    Reduce finite String vocabularies for attributes that are unused by this property check.

    Safety: only attributes with finite String vocab that are not read/written by any
    relevant rule/property expression are reduced (to one representative literal).
    This is semantics-preserving for satisfiability because those attributes are never
    observed by constraints beyond domain membership.
    """
    new_classes: list[Class] = []
    changed = False
    for cls in mm.classes:
        new_attrs: list[Attribute] = []
        for attr in cls.attributes:
            if (
                (attr.type or "").strip().lower() == "string"
                and attr.string_vocab
                and len(attr.string_vocab) > 1
                and (cls.name, attr.name) not in used_attrs
            ):
                new_attrs.append(replace(attr, string_vocab=(attr.string_vocab[0],)))
                changed = True
            else:
                new_attrs.append(attr)
        if tuple(new_attrs) != cls.attributes:
            new_classes.append(replace(cls, attributes=tuple(new_attrs)))
        else:
            new_classes.append(cls)
    if not changed:
        return mm
    return replace(mm, classes=tuple(new_classes))


def _reduce_unused_string_vocabs_for_property(
    transformation: Transformation,
    prop: Property,
    relevant_rules: Optional[Set[RuleId]],
) -> Transformation:
    """
    Return a transformation with unused finite String vocabularies collapsed.

    This is a conservative, exact optimization (not an abstraction): only unused
    finite String attributes are reduced.
    """
    used_src, used_tgt = _collect_used_string_attrs_for_property(
        transformation, prop, relevant_rules
    )
    new_src = _reduce_unused_string_vocab_in_metamodel(transformation.source_metamodel, used_src)
    new_tgt = _reduce_unused_string_vocab_in_metamodel(transformation.target_metamodel, used_tgt)
    if new_src is transformation.source_metamodel and new_tgt is transformation.target_metamodel:
        return transformation
    return replace(
        transformation,
        source_metamodel=new_src,
        target_metamodel=new_tgt,
    )


def _compute_trace_consumer_type_pairs(
    transformation: Transformation,
    prop: Property,
    relevant_rules: Optional[Set[RuleId]],
) -> Set[Tuple[str, str]]:
    """
    Compute consumed trace type pairs (source_class_name, target_class_name).

    A pair is consumed iff it appears in:
    - a backward link of an encoded rule, or
    - a property postcondition trace link.
    """
    source_name_map: Dict[str, str] = {}
    for c in transformation.source_metamodel.classes:
        source_name_map[str(c.id)] = c.name
        source_name_map[c.name] = c.name

    target_name_map: Dict[str, str] = {}
    for c in transformation.target_metamodel.classes:
        target_name_map[str(c.id)] = c.name
        target_name_map[c.name] = c.name

    def src_name(cls_id) -> str:
        key = str(cls_id)
        return source_name_map.get(key, key)

    def tgt_name(cls_id) -> str:
        key = str(cls_id)
        return target_name_map.get(key, key)

    pairs: Set[Tuple[str, str]] = set()

    for layer in transformation.layers:
        for rule in layer.rules:
            if relevant_rules is not None and rule.id not in relevant_rules:
                continue
            for bl in rule.backward_links:
                me = rule.match_element_by_id.get(bl.match_element)
                ae = rule.apply_element_by_id.get(bl.apply_element)
                if me is None or ae is None:
                    continue
                pairs.add((src_name(me.class_type), tgt_name(ae.class_type)))

    pre = prop.precondition
    post = prop.postcondition
    if pre is not None:
        pre_by_id = {str(e.id): e for e in pre.elements}
        post_by_id = {str(e.id): e for e in post.elements}
        for post_elem_id, pre_elem_id in post.trace_links:
            post_elem = post_by_id.get(str(post_elem_id))
            pre_elem = pre_by_id.get(str(pre_elem_id))
            if post_elem is None or pre_elem is None:
                continue
            pairs.add((src_name(pre_elem.class_type), tgt_name(post_elem.class_type)))

    return pairs


def _compute_per_class_type_bounds(
    transformation: Transformation,
    prop: Property,
    relevant_rules: Optional[Set[RuleId]],
    global_bound: int,
    analysis_mode: str = "simple",
    relevant_src_classes: Optional[Set[str]] = None,
    relevant_tgt_classes: Optional[Set[str]] = None,
) -> tuple[Dict[str, int], Dict[str, int]]:
    """
    Compute per-class bounds for source/target classes.

    The current implementation uses the fixed-point profile aligned with the
    theorem document: source precondition seeds + mandatory source closure,
    followed by target production counts + mandatory target closure, all capped
    by the global cutoff bound. ``analysis_mode`` is currently kept only for
    backward-compatible API compatibility; both ``"simple"`` and
    ``"fixed_point"`` dispatch to the same theorem-aligned calculation.
    """
    relevant_rule_ids: Set[RuleId]
    if relevant_rules is None:
        relevant_rule_ids = {r.id for r in transformation.all_rules}
    else:
        relevant_rule_ids = set(relevant_rules)

    if analysis_mode not in {"simple", "fixed_point"}:
        raise ValueError(f"Unknown per_class_bounds_analysis: {analysis_mode}")

    return compute_per_class_slot_bounds_fixed_point(
        transformation=transformation,
        property=prop,
        relevant_rule_ids=relevant_rule_ids,
        global_bound=global_bound,
        relevant_src_classes=relevant_src_classes,
        relevant_tgt_classes=relevant_tgt_classes,
    )


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

@dataclass
class SMTDirectConfig:
    """Configuration for direct SMT verification."""
    # Bound on number of elements per type (fallback when cutoff not used)
    bound: int = 5

    # Use cutoff theorem: when (T, P) is in F-LNR × G-BPP, use property-specific K as bound
    use_cutoff: bool = True

    # Cap on cutoff bound for tractability (None = no cap)
    max_cutoff_bound: Optional[int] = None
    
    # Z3 timeout per property (ms). None or 0 = no timeout (run until sat/unsat).
    timeout_ms: Optional[int] = 30000

    # Z3 solver logic (e.g. "QF_UF", "QF_BV"); None = default solver
    solver_logic: Optional[str] = None

    # Z3 random seed for reproducibility / trying different heuristics (None = default)
    random_seed: Optional[int] = None

    # Encode only rules relevant to the property (smaller formula, may get sat/unsat instead of unknown)
    use_property_slicing: bool = False

    # Dependency mode for rule relevance and slicing
    dependency_mode: str = "legacy"

    # Solver backend: "z3" (default) or "cvc5" (export to SMT-LIB2 and run cvc5 binary)
    solver_backend: str = "z3"

    # Check property by one violation candidate at a time (push/add/check/pop). Reduces formula
    # size per check and can scale better for large bounds. Only used when solver_backend=="z3".
    use_incremental_property_check: bool = False

    # Conservatively fall back to exact incremental checking when the monolithic
    # property encoding shape looks likely to defeat one large solver check.
    auto_incremental_fallback: bool = True

    # Conservative fallback thresholds: only switch when there are few candidate
    # violations but many unfactored post bindings to search through.
    auto_incremental_max_pre_bindings: int = 4
    auto_incremental_max_violation_count: int = 4
    auto_incremental_min_post_full_bindings: int = 20000

    # Z3 tactic name(s) to build solver, e.g. "smt", "qflia", or "simplify" then "smt".
    # None = default solver. Only used when solver_backend=="z3".
    solver_tactic: Optional[str] = None

    # Enable metamodel slicing: only create SMT variables for classes and associations
    # actually referenced by the relevant rules and property. Requires use_property_slicing=True.
    use_metamodel_slicing: bool = False

    # Optional SMT symmetry breaking for postcondition component bindings.
    # Applies only to provably interchangeable post elements (same class,
    # no incident post links, same trace-pre set).
    enable_property_symmetry_breaking: bool = False

    # Reduce finite String vocabularies for attributes unused by relevant rule/property
    # constraints. This is an exact optimization for unused attributes.
    reduce_unused_string_domains: bool = False

    # Register trace producers only for source/target type pairs that are
    # consumed by this property check (backward links or property trace links).
    # This is semantics-preserving and can significantly reduce formula size.
    prune_unconsumed_trace_producers: bool = False

    # Delay exact target-world closure until a SAT model actually uses unjustified
    # target nodes/links. This is an exact refinement loop for Z3 backends.
    lazy_target_world_refinement: bool = True

    # Per-class mode: use theorem-aligned source/target class bounds to shrink
    # formulas instead of a uniform global K per class.
    use_per_class_type_bounds: bool = False

    # Per-class bounds analysis profile:
    # - "simple": alias of the fixed-point profile for backward compatibility.
    # - "fixed_point": source seed + source closure + target production +
    #   target mandatory closure.
    per_class_bounds_analysis: str = "simple"

    # Completeness policy for per-class bounds:
    # - "aggressive_optimized": keep current behavior and report incomplete
    #   even though formulas are reduced aggressively.
    # - "strict_theorem": treat the theorem-aligned fixed-point per-class bounds
    #   as completeness-preserving when all other cutoff conditions hold.
    per_class_bound_mode: str = "aggressive_optimized"

    # Heuristic mode: relax source containment participation constraints to
    # reduce search space and often reduce K (by ignoring containment in arity).
    # This mode is not completeness-preserving for cutoff claims.
    relax_source_containment_for_proving: bool = False

    # When relaxed mode finds SAT (candidate violation), re-run with strict
    # containment semantics to filter spurious counterexamples.
    strict_recheck_on_relaxed_sat: bool = True
    
    # Enable verbose output
    verbose: bool = False


# -----------------------------------------------------------------------------
# Result Types
# -----------------------------------------------------------------------------

@dataclass
class LazyTargetWorldRefinementBatch:
    """Exact closure constraints discovered from one SAT model."""
    constraints: Tuple[z3.BoolRef, ...] = ()
    refined_target_nodes: int = 0
    refined_target_links: int = 0


@dataclass
class PropertySolverStats:
    """Per-property solver instrumentation for tractability analysis."""
    encoding_ms: float = 0.0
    relevance_ms: float = 0.0
    string_reduction_ms: float = 0.0
    metamodel_slice_ms: float = 0.0
    per_class_bounds_ms: float = 0.0
    model_encoder_ms: float = 0.0
    rule_encoder_ms: float = 0.0
    property_encoder_ms: float = 0.0
    check_ms: float = 0.0
    refinement_ms: float = 0.0
    counterexample_ms: float = 0.0
    solver_calls: int = 0
    refinement_model_inspections: int = 0
    refinement_rounds: int = 0
    refinement_clauses: int = 0
    refined_target_nodes: int = 0
    refined_target_links: int = 0
    pre_bindings: int = 0
    violation_count: int = 0
    post_components: int = 0
    post_component_bindings: int = 0
    post_full_bindings: int = 0
    used_factored_post: bool = False
    incremental_candidates_total: int = 0
    incremental_candidates_checked: int = 0
    incremental_candidates_unsat: int = 0
    incremental_candidates_sat: int = 0
    incremental_candidates_unknown: int = 0
    phase: str = "init"
    exception_phase: str = ""
    auto_incremental_fallback_suggested: bool = False
    auto_incremental_fallback_used: bool = False
    auto_incremental_fallback_reason: str = ""


@dataclass
class PropertyEncodingStats:
    """Structural stats collected while encoding one property."""
    pre_bindings: int = 0
    violation_count: int = 0
    post_components: int = 0
    post_component_bindings: int = 0
    post_full_bindings: int = 0
    used_factored_post: bool = False


@dataclass
class PropertyVerificationResult:
    """Result of verifying a single property."""
    property_id: str
    property_name: str
    result: CheckResult
    time_ms: float
    counterexample: Optional[dict] = None
    message: str = ""
    # Cutoff: when True, verification at bound_used is complete for all model sizes
    is_complete: bool = False
    bound_used: int = 0
    cutoff_K: Optional[int] = None
    stats: PropertySolverStats = field(default_factory=PropertySolverStats)


@dataclass
class DirectVerificationResult:
    """Result of verifying all properties in a transformation."""
    transformation_name: str
    bound: int  # Default/fallback bound
    property_results: Tuple[PropertyVerificationResult, ...]
    total_time_ms: float
    holds_count: int = 0
    violated_count: int = 0
    unknown_count: int = 0
    complete_count: int = 0  # Properties verified with cutoff (complete)


_AUTO_INCREMENTAL_FALLBACK_SENTINEL = "__auto_incremental_fallback__"


# -----------------------------------------------------------------------------
# SMT Model Encoder
# -----------------------------------------------------------------------------

class SMTModelEncoder:
    """
    Encodes source and target metamodels as bounded SMT variables.
    
    Creates:
      - exists_<Type>[i] for element existence
      - <relation>[s][t] for associations
      - trace_<src>_<tgt>[s][t] for trace links
      - Well-formedness constraints
    """
    
    def __init__(
        self,
        source_mm: Metamodel,
        target_mm: Metamodel,
        bound: int,
        solver: z3.Solver,
        source_class_bounds: Optional[Dict[str, int]] = None,
        target_class_bounds: Optional[Dict[str, int]] = None,
        relevant_src_classes: Optional[Set[str]] = None,
        relevant_tgt_classes: Optional[Set[str]] = None,
        relevant_src_assocs: Optional[Set[str]] = None,
        relevant_tgt_assocs: Optional[Set[str]] = None,
        relax_source_containment_participation: bool = False,
    ):
        self.source_mm = source_mm
        self.target_mm = target_mm
        self.bound = bound
        self.solver = solver
        self.source_class_bounds = source_class_bounds or {}
        self.target_class_bounds = target_class_bounds or {}
        self.encoding_issues: List[str] = []
        
        # Metamodel slicing: if provided, only create variables for these classes/assocs.
        self._rel_src_cls = relevant_src_classes
        self._rel_tgt_cls = relevant_tgt_classes
        self._rel_src_assoc = relevant_src_assocs
        self._rel_tgt_assoc = relevant_tgt_assocs
        self._relax_source_containment_participation = relax_source_containment_participation
        
        # Variable storage - use class NAME as key for easier lookup
        self.source_exists: Dict[str, List[z3.BoolRef]] = {}
        self.source_relations: Dict[str, List[List[z3.BoolRef]]] = {}
        self.source_attrs: Dict[Tuple[str, str], List[z3.ExprRef]] = {}
        
        self.target_exists: Dict[str, List[z3.BoolRef]] = {}
        self.target_relations: Dict[str, List[List[z3.BoolRef]]] = {}
        self.target_attrs: Dict[Tuple[str, str], List[z3.ExprRef]] = {}
        # Optional trace matrix storage kept for compatibility/debug tooling.
        # D9 removes its use from rule postcondition encoding.
        self.trace_links: Dict[Tuple[str, str], List[List[z3.BoolRef]]] = {}
        
        # Cache finite enum-like domains as string values for each metamodel enum.
        self._enum_vocab_cache: Dict[Tuple[str, str], Tuple[str, ...]] = {}
        
        # Class name to ID mapping
        self.source_class_names: Set[str] = set()
        self.target_class_names: Set[str] = set()
        
        # Encode models
        self._encode_source_model()
        self._encode_target_model()

    def source_bound_for(self, cls_name: str) -> int:
        """Per-source-class bound, defaulting to global bound."""
        return max(1, self.source_class_bounds.get(cls_name, self.bound))

    def target_bound_for(self, cls_name: str) -> int:
        """Per-target-class bound, defaulting to global bound."""
        return max(1, self.target_class_bounds.get(cls_name, self.bound))

    def _iter_effective_attributes(self, mm: Metamodel, cls: Class) -> tuple[Attribute, ...]:
        """Return class attributes including inherited ones (child-first, deduplicated)."""
        attrs: list[Attribute] = []
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
    
    def _encode_source_model(self):
        """Encode source metamodel as SMT variables (optionally sliced)."""
        # Create existence variables for each class (skip if not relevant)
        for cls in self.source_mm.classes:
            if self._rel_src_cls is not None and cls.name not in self._rel_src_cls:
                continue
            N = self.source_bound_for(cls.name)
            self.source_class_names.add(cls.name)
            self.source_exists[cls.name] = [
                z3.Bool(f"src_{cls.name}_{i}") for i in range(N)
            ]
            # Create attribute variables (including inherited attributes)
            for attr in self._iter_effective_attributes(self.source_mm, cls):
                key = (cls.name, attr.name)
                self.source_attrs[key] = [
                    self._create_attr_var(f"src_{cls.name}_{i}_{attr.name}", attr)
                    for i in range(N)
                ]
                self._add_attr_domain_constraints(
                    exists_vars=self.source_exists[cls.name],
                    attr_vars=self.source_attrs[key],
                    attr=attr,
                    mm=self.source_mm,
                )
        
        # Create association variables (skip if not relevant)
        for assoc in self.source_mm.associations:
            if self._rel_src_assoc is not None and assoc.name not in self._rel_src_assoc:
                continue
            src_cls_name = self._get_class_name(self.source_mm, assoc.source_class)
            tgt_cls_name = self._get_class_name(self.source_mm, assoc.target_class)
            if not src_cls_name or not tgt_cls_name:
                continue
            src_n = self.source_bound_for(src_cls_name)
            tgt_n = self.source_bound_for(tgt_cls_name)
            self.source_relations[assoc.name] = [
                [z3.Bool(f"src_{assoc.name}_{s}_{t}") for t in range(tgt_n)]
                for s in range(src_n)
            ]
            # Well-formedness: association requires both endpoints to exist
            if src_cls_name in self.source_exists and tgt_cls_name in self.source_exists:
                for s in range(src_n):
                    for t in range(tgt_n):
                        self.solver.add(z3.Implies(
                            self.source_relations[assoc.name][s][t],
                            z3.And(
                                self.source_exists[src_cls_name][s],
                                self.source_exists[tgt_cls_name][t]
                            )
                        ))
        
        # Mandatory participation: if multiplicity on an end has min >= 1, every
        # instance of that end must participate in at least one link.
        self._add_source_mandatory_participation()
    
    def _add_source_mandatory_participation(self) -> None:
        """Add constraints: every source/target instance that must participate in
        an association (multiplicity min >= 1 on the opposite end) is in at least one link.

        Containment semantics: an element can only have one containment parent.
        So containment associations targeting the same class are grouped with OR
        (element is in one of them). Non-containment associations with source_mult >= 1
        are independent constraints (each must be satisfied individually).
        """
        # Target participation: split into containment and non-containment groups.
        # Containment associations targeting the same class -> OR (one parent)
        # Non-containment associations -> individual AND constraints
        containment_target_to_assocs: Dict[str, List[str]] = defaultdict(list)
        for assoc in self.source_mm.associations:
            if assoc.source_mult[0] < 1:
                continue
            tgt_cls_name = self._get_class_name(self.source_mm, assoc.target_class)
            if not tgt_cls_name or tgt_cls_name not in self.source_exists:
                continue
            if assoc.name not in self.source_relations:
                continue
            if assoc.is_containment:
                if self._relax_source_containment_participation:
                    continue
                containment_target_to_assocs[tgt_cls_name].append(assoc.name)
            else:
                # Non-containment: each association is an independent constraint
                tgt_n = len(self.source_exists[tgt_cls_name])
                src_cls_name = self._get_class_name(self.source_mm, assoc.source_class)
                if not src_cls_name or src_cls_name not in self.source_exists:
                    continue
                src_n = len(self.source_exists[src_cls_name])
                for t in range(tgt_n):
                    self.solver.add(z3.Implies(
                        self.source_exists[tgt_cls_name][t],
                        z3.Or([self.source_relations[assoc.name][s][t] for s in range(src_n)])
                    ))
        # Containment: group by target class (element has exactly one containment parent)
        for tgt_cls_name, assoc_names in containment_target_to_assocs.items():
            tgt_n = len(self.source_exists[tgt_cls_name])
            for t in range(tgt_n):
                participation = z3.Or([
                    z3.Or([
                        self.source_relations[aname][s][t]
                        for s in range(len(self.source_relations[aname]))
                    ])
                    for aname in assoc_names
                ])
                self.solver.add(z3.Implies(
                    self.source_exists[tgt_cls_name][t],
                    participation
                ))
        # Source participation: each source must have >= target_mult[0] targets (per association)
        for assoc in self.source_mm.associations:
            src_cls_name = self._get_class_name(self.source_mm, assoc.source_class)
            tgt_cls_name = self._get_class_name(self.source_mm, assoc.target_class)
            if not src_cls_name or src_cls_name not in self.source_exists:
                continue
            if not tgt_cls_name or tgt_cls_name not in self.source_exists:
                continue
            rel = self.source_relations.get(assoc.name)
            if not rel or assoc.target_mult[0] < 1:
                continue
            tgt_n = len(rel[0]) if rel and rel[0] else 0
            for s in range(len(rel)):
                if assoc.target_mult[0] >= 2:
                    at_least_two = z3.Or([
                        z3.And(rel[s][t1], rel[s][t2])
                        for t1 in range(tgt_n) for t2 in range(tgt_n) if t1 != t2
                    ])
                    self.solver.add(z3.Implies(
                        self.source_exists[src_cls_name][s],
                        at_least_two
                    ))
                else:
                    self.solver.add(z3.Implies(
                        self.source_exists[src_cls_name][s],
                        z3.Or([rel[s][t] for t in range(tgt_n)])
                    ))
    
    def _encode_target_model(self):
        """Encode target metamodel as SMT variables (optionally sliced)."""
        # Create existence variables for each class (skip if not relevant)
        for cls in self.target_mm.classes:
            if self._rel_tgt_cls is not None and cls.name not in self._rel_tgt_cls:
                continue
            N = self.target_bound_for(cls.name)
            self.target_class_names.add(cls.name)
            self.target_exists[cls.name] = [
                z3.Bool(f"tgt_{cls.name}_{i}") for i in range(N)
            ]
            # Create attribute variables (including inherited attributes)
            for attr in self._iter_effective_attributes(self.target_mm, cls):
                key = (cls.name, attr.name)
                self.target_attrs[key] = [
                    self._create_attr_var(f"tgt_{cls.name}_{i}_{attr.name}", attr)
                    for i in range(N)
                ]
                self._add_attr_domain_constraints(
                    exists_vars=self.target_exists[cls.name],
                    attr_vars=self.target_attrs[key],
                    attr=attr,
                    mm=self.target_mm,
                )
        
        # Create association variables (skip if not relevant)
        for assoc in self.target_mm.associations:
            if self._rel_tgt_assoc is not None and assoc.name not in self._rel_tgt_assoc:
                continue
            src_cls_name = self._get_class_name(self.target_mm, assoc.source_class)
            tgt_cls_name = self._get_class_name(self.target_mm, assoc.target_class)
            if not src_cls_name or not tgt_cls_name:
                continue
            src_n = self.target_bound_for(src_cls_name)
            tgt_n = self.target_bound_for(tgt_cls_name)
            self.target_relations[assoc.name] = [
                [z3.Bool(f"tgt_{assoc.name}_{s}_{t}") for t in range(tgt_n)]
                for s in range(src_n)
            ]
            # Well-formedness
            if src_cls_name in self.target_exists and tgt_cls_name in self.target_exists:
                for s in range(src_n):
                    for t in range(tgt_n):
                        self.solver.add(z3.Implies(
                            self.target_relations[assoc.name][s][t],
                            z3.And(
                                self.target_exists[src_cls_name][s],
                                self.target_exists[tgt_cls_name][t]
                            )
                        ))
    
    def _get_class_name(self, mm: Metamodel, cls_id: ClassId) -> Optional[str]:
        """Get class name from ID."""
        for c in mm.classes:
            if c.id == cls_id or c.name == cls_id:
                return c.name
        return None

    def _enum_vocab(self, mm: Metamodel, enum_name: str) -> Tuple[str, ...]:
        key = (mm.name, enum_name)
        if key in self._enum_vocab_cache:
            return self._enum_vocab_cache[key]
        enum_def = mm.enum_by_name.get(enum_name)
        if enum_def is None:
            self._enum_vocab_cache[key] = tuple()
        else:
            self._enum_vocab_cache[key] = tuple(enum_def.literals)
        return self._enum_vocab_cache[key]

    def _create_attr_var(self, var_name: str, attr: Attribute) -> z3.ExprRef:
        """Create SMT var for an attribute with finite-domain-aware typing."""
        t = (attr.type or "").strip()
        tl = t.lower()
        if tl in ("bool", "boolean"):
            return z3.Bool(var_name)
        if tl in ("string",):
            return z3.String(var_name)
        # Int/Real and custom numeric-like types remain Int for tractability.
        if tl in ("int", "integer", "real", "float"):
            return z3.Int(var_name)
        # Enum-typed attributes are encoded as finite symbolic strings.
        return z3.String(var_name)

    def _add_attr_domain_constraints(
        self,
        exists_vars: List[z3.BoolRef],
        attr_vars: List[z3.ExprRef],
        attr: Attribute,
        mm: Metamodel,
    ) -> None:
        """Constrain attribute values to declared finite domains when element exists."""
        t = (attr.type or "").strip()
        tl = t.lower()
        for i, v in enumerate(attr_vars):
            ex = exists_vars[i]
            if tl in ("int", "integer") and attr.int_range is not None:
                lo, hi = attr.int_range
                self.solver.add(z3.Implies(ex, z3.And(v >= lo, v <= hi)))
            elif tl == "string" and attr.string_vocab:
                allowed = [v == z3.StringVal(s) for s in attr.string_vocab]
                self.solver.add(z3.Implies(ex, z3.Or(allowed)))
            else:
                # Enum declarations are finite domains as symbolic names.
                enum_vals = self._enum_vocab(mm, t)
                if enum_vals:
                    allowed = [v == z3.StringVal(s) for s in enum_vals]
                    self.solver.add(z3.Implies(ex, z3.Or(allowed)))
    
    def get_source_exists(self, cls_id: str) -> Optional[List[z3.BoolRef]]:
        """Get existence variables for a source class."""
        # Try direct name match
        if cls_id in self.source_exists:
            return self.source_exists[cls_id]
        # Try as ClassId
        name = self._get_class_name(self.source_mm, ClassId(cls_id))
        if name and name in self.source_exists:
            return self.source_exists[name]
        return None
    
    def get_target_exists(self, cls_id: str) -> Optional[List[z3.BoolRef]]:
        """Get existence variables for a target class."""
        if cls_id in self.target_exists:
            return self.target_exists[cls_id]
        name = self._get_class_name(self.target_mm, ClassId(cls_id))
        if name and name in self.target_exists:
            return self.target_exists[name]
        return None
    
    def get_source_relation(self, assoc_name: str) -> Optional[List[List[z3.BoolRef]]]:
        """Get relation variables for a source association."""
        if assoc_name in self.source_relations:
            return self.source_relations[assoc_name]
        return None
    
    def get_target_relation(self, assoc_name: str) -> Optional[List[List[z3.BoolRef]]]:
        """Get relation variables for a target association."""
        if assoc_name in self.target_relations:
            return self.target_relations[assoc_name]
        return None

    def create_trace_link(self, src_cls: str, tgt_cls: str) -> List[List[z3.BoolRef]]:
        """Create or retrieve trace link variables between source and target types."""
        key = (src_cls, tgt_cls)
        if key not in self.trace_links:
            src_n = self.source_bound_for(src_cls)
            tgt_n = self.target_bound_for(tgt_cls)
            self.trace_links[key] = [
                [z3.Bool(f"trace_{src_cls}_{tgt_cls}_{s}_{t}") for t in range(tgt_n)]
                for s in range(src_n)
            ]
        return self.trace_links[key]
    
    def get_source_attr(self, cls_name: str, attr_name: str) -> Optional[List[z3.ExprRef]]:
        """Get attribute variables for a source class attribute."""
        key = (cls_name, attr_name)
        return self.source_attrs.get(key)

    def get_target_attr(self, cls_name: str, attr_name: str) -> Optional[List[z3.ExprRef]]:
        """Get attribute variables for a target class attribute."""
        key = (cls_name, attr_name)
        return self.target_attrs.get(key)


# -----------------------------------------------------------------------------
# SMT Rule Encoder
# -----------------------------------------------------------------------------

class SMTRuleEncoder:
    """
    Encodes rule firing semantics with the 4 DSLTrans cases.
    
    Key improvement: For rules with N match elements, we enumerate
    all N-tuples of source element indices as potential match bindings.
    """
    
    def __init__(
        self,
        transformation: Transformation,
        model_encoder: SMTModelEncoder,
        solver: z3.Solver,
        relevant_rules: Optional[Set[RuleId]] = None,
        trace_consumer_pairs: Optional[Set[Tuple[str, str]]] = None,
        prune_unconsumed_trace_producers: bool = False,
        eager_target_world_closure: bool = True,
    ):
        self.transformation = transformation
        self.model = model_encoder
        self.solver = solver
        self.bound = model_encoder.bound
        self.relevant_rules = relevant_rules
        self.trace_consumer_pairs = trace_consumer_pairs
        self.prune_unconsumed_trace_producers = prune_unconsumed_trace_producers
        self.eager_target_world_closure = eager_target_world_closure
        self.layer_count = len(self.transformation.layers)
        
        # Firing variables: fires_<rule>_<binding>
        # For multi-element rules, binding is a tuple of indices
        self.fires: Dict[RuleId, Dict[tuple, z3.BoolRef]] = {}
        
        # Accumulated attribute constraints (Θ_attr)
        self.theta_attr: List[z3.BoolRef] = []
        
        # Element name to index mapping for each rule firing
        self.element_bindings: Dict[RuleId, Dict[tuple, Dict[str, int]]] = {}
        # Created target-slot selections:
        # (tgt_cls, tgt_idx) -> list[choice_var]
        # Used to prevent two distinct rule firings from creating the same target slot.
        self.created_target_assignments: Dict[Tuple[str, int], List[z3.BoolRef]] = defaultdict(list)
        # Closed target-world bookkeeping:
        # target nodes/links may exist iff some encoded rule firing justifies them.
        self.target_node_justifiers: Dict[Tuple[str, int], List[z3.BoolRef]] = defaultdict(list)
        self.target_link_justifiers: Dict[Tuple[str, int, int], List[z3.BoolRef]] = defaultdict(list)
        self._lazy_refined_target_nodes: Set[Tuple[str, int]] = set()
        self._lazy_refined_target_links: Set[Tuple[str, int, int]] = set()
        # Trace producer provenance:
        # (src_cls, tgt_cls, src_idx, tgt_idx) -> list[(layer_idx, fires_var)]
        # Used to enforce layer-isolated backward-link visibility and exact trace semantics.
        self.trace_producers: Dict[Tuple[str, str, int, int], List[Tuple[int, z3.BoolRef]]] = defaultdict(list)
        self.trace_producers_by_layer: Dict[Tuple[int, str, str, int, int], List[z3.BoolRef]] = defaultdict(list)
        # Fast trace-state variables:
        # (src_cls, tgt_cls, boundary_layer, src_idx, tgt_idx) -> Bool
        # boundary_layer=0 means "before layer 0"; boundary_layer=layer_count means final state.
        self.trace_before_layer_vars: Dict[Tuple[str, str, int, int, int], z3.BoolRef] = {}
        if self.trace_consumer_pairs is not None:
            self._init_trace_state_vars()
        
        # Encode all rules (or only relevant ones if property slicing)
        self._encode_all_rules()
        self._finalize_created_target_constraints()
        if self.eager_target_world_closure:
            self._finalize_target_world_constraints()
        if self.trace_consumer_pairs is not None:
            self._finalize_trace_state_constraints()

    def _source_bound_for(self, cls_name: str) -> int:
        return self.model.source_bound_for(cls_name)

    def _target_bound_for(self, cls_name: str) -> int:
        return self.model.target_bound_for(cls_name)

    def _register_trace_producer(
        self,
        layer_idx: int,
        src_cls: str,
        tgt_cls: str,
        src_idx: int,
        tgt_idx: int,
        fires_var: z3.BoolRef,
    ) -> None:
        key = (src_cls, tgt_cls, src_idx, tgt_idx)
        self.trace_producers[key].append((layer_idx, fires_var))
        layer_key = (layer_idx, src_cls, tgt_cls, src_idx, tgt_idx)
        self.trace_producers_by_layer[layer_key].append(fires_var)

    def _register_created_target_assignment(
        self,
        tgt_cls: str,
        tgt_idx: int,
        choice_var: z3.BoolRef,
    ) -> None:
        self.created_target_assignments[(tgt_cls, tgt_idx)].append(choice_var)

    def _finalize_created_target_constraints(self) -> None:
        """A target slot can be created by at most one rule/apply/binding."""
        for choice_vars in self.created_target_assignments.values():
            if len(choice_vars) > 1:
                self.solver.add(z3.PbLe([(v, 1) for v in choice_vars], 1))

    def _register_target_node_justifier(
        self,
        tgt_cls: str,
        tgt_idx: int,
        justification: z3.BoolRef,
    ) -> None:
        self.target_node_justifiers[(tgt_cls, tgt_idx)].append(justification)

    def _register_target_link_justifier(
        self,
        assoc_name: str,
        src_idx: int,
        tgt_idx: int,
        justification: z3.BoolRef,
    ) -> None:
        self.target_link_justifiers[(assoc_name, src_idx, tgt_idx)].append(justification)

    def _finalize_target_world_constraints(self) -> None:
        """
        Close the target world so target nodes/links require rule justification.

        Justifier -> target existence/link presence is already added when rules
        encode their postconditions. So the closure only needs the reverse
        direction (target present -> some justifier), rather than a full
        equivalence.
        """
        for cls_name, exists_vars in self.model.target_exists.items():
            for tgt_idx, exists_var in enumerate(exists_vars):
                justifiers = self.target_node_justifiers.get((cls_name, tgt_idx), [])
                if justifiers:
                    self.solver.add(z3.Implies(exists_var, z3.Or(justifiers)))
                else:
                    self.solver.add(z3.Not(exists_var))

        for assoc_name, matrix in self.model.target_relations.items():
            for src_idx, row in enumerate(matrix):
                for tgt_idx, rel_var in enumerate(row):
                    justifiers = self.target_link_justifiers.get((assoc_name, src_idx, tgt_idx), [])
                    if justifiers:
                        self.solver.add(z3.Implies(rel_var, z3.Or(justifiers)))
                    else:
                        self.solver.add(z3.Not(rel_var))

    def _target_node_closure_constraint(self, cls_name: str, tgt_idx: int) -> z3.BoolRef:
        exists_var = self.model.target_exists[cls_name][tgt_idx]
        justifiers = self.target_node_justifiers.get((cls_name, tgt_idx), [])
        if justifiers:
            return z3.Implies(exists_var, z3.Or(justifiers))
        return z3.Not(exists_var)

    def _target_link_closure_constraint(
        self,
        assoc_name: str,
        src_idx: int,
        tgt_idx: int,
    ) -> z3.BoolRef:
        rel_var = self.model.target_relations[assoc_name][src_idx][tgt_idx]
        justifiers = self.target_link_justifiers.get((assoc_name, src_idx, tgt_idx), [])
        if justifiers:
            return z3.Implies(rel_var, z3.Or(justifiers))
        return z3.Not(rel_var)

    def target_world_refinements_for_model(
        self,
        z3_model: z3.ModelRef,
    ) -> LazyTargetWorldRefinementBatch:
        """
        Return exact target-world closure constraints violated by the current SAT
        model. Adding these constraints refines the solver without changing the
        semantics of the encoding.
        """
        refinements: List[z3.BoolRef] = []
        refined_target_nodes = 0
        refined_target_links = 0

        for cls_name, exists_vars in self.model.target_exists.items():
            for tgt_idx, exists_var in enumerate(exists_vars):
                key = (cls_name, tgt_idx)
                if key in self._lazy_refined_target_nodes:
                    continue
                if not z3.is_true(z3_model.eval(exists_var, model_completion=True)):
                    continue
                justifiers = self.target_node_justifiers.get(key, [])
                if any(z3.is_true(z3_model.eval(j, model_completion=True)) for j in justifiers):
                    continue
                refinements.append(self._target_node_closure_constraint(cls_name, tgt_idx))
                self._lazy_refined_target_nodes.add(key)
                refined_target_nodes += 1

        for assoc_name, matrix in self.model.target_relations.items():
            for src_idx, row in enumerate(matrix):
                for tgt_idx, rel_var in enumerate(row):
                    key = (assoc_name, src_idx, tgt_idx)
                    if key in self._lazy_refined_target_links:
                        continue
                    if not z3.is_true(z3_model.eval(rel_var, model_completion=True)):
                        continue
                    justifiers = self.target_link_justifiers.get(key, [])
                    if any(z3.is_true(z3_model.eval(j, model_completion=True)) for j in justifiers):
                        continue
                    refinements.append(
                        self._target_link_closure_constraint(assoc_name, src_idx, tgt_idx)
                    )
                    self._lazy_refined_target_links.add(key)
                    refined_target_links += 1

        return LazyTargetWorldRefinementBatch(
            constraints=tuple(refinements),
            refined_target_nodes=refined_target_nodes,
            refined_target_links=refined_target_links,
        )

    def _init_trace_state_vars(self) -> None:
        """Create per-layer trace-state variables for consumed trace type pairs."""
        for src_cls, tgt_cls in self.trace_consumer_pairs or set():
            src_n = self._source_bound_for(src_cls)
            tgt_n = self._target_bound_for(tgt_cls)
            for boundary_layer in range(self.layer_count + 1):
                for src_idx in range(src_n):
                    for tgt_idx in range(tgt_n):
                        name = f"trace_before_{boundary_layer}_{src_cls}_{tgt_cls}_{src_idx}_{tgt_idx}"
                        self.trace_before_layer_vars[(src_cls, tgt_cls, boundary_layer, src_idx, tgt_idx)] = z3.Bool(name)

    def _finalize_trace_state_constraints(self) -> None:
        """
        Add recurrence constraints for per-layer trace-state variables.

        trace_before[0] is false. For each layer L:
          trace_before[L+1] = trace_before[L] OR any producer firing in layer L.
        """
        for src_cls, tgt_cls in self.trace_consumer_pairs or set():
            src_n = self._source_bound_for(src_cls)
            tgt_n = self._target_bound_for(tgt_cls)
            for src_idx in range(src_n):
                for tgt_idx in range(tgt_n):
                    t0 = self.trace_before_layer_vars[(src_cls, tgt_cls, 0, src_idx, tgt_idx)]
                    self.solver.add(t0 == z3.BoolVal(False))
                    for layer_idx in range(self.layer_count):
                        prev_t = self.trace_before_layer_vars[(src_cls, tgt_cls, layer_idx, src_idx, tgt_idx)]
                        next_t = self.trace_before_layer_vars[(src_cls, tgt_cls, layer_idx + 1, src_idx, tgt_idx)]
                        layer_key = (layer_idx, src_cls, tgt_cls, src_idx, tgt_idx)
                        producers = self.trace_producers_by_layer.get(layer_key, [])
                        if producers:
                            self.solver.add(next_t == z3.Or(prev_t, z3.Or(producers)))
                        else:
                            self.solver.add(next_t == prev_t)

    def trace_visible_before_layer(
        self,
        layer_idx: int,
        src_cls: str,
        tgt_cls: str,
        src_idx: int,
        tgt_idx: int,
    ) -> z3.BoolRef:
        """Trace visibility for backward links: only producers from earlier layers."""
        if self.trace_consumer_pairs is not None:
            if (src_cls, tgt_cls) not in self.trace_consumer_pairs:
                return z3.BoolVal(False)
            key = (src_cls, tgt_cls, layer_idx, src_idx, tgt_idx)
            return self.trace_before_layer_vars.get(key, z3.BoolVal(False))
        key = (src_cls, tgt_cls, src_idx, tgt_idx)
        lits = [f for l, f in self.trace_producers.get(key, []) if l < layer_idx]
        if not lits:
            return z3.BoolVal(False)
        return z3.Or(lits)

    def trace_holds(
        self,
        src_cls: str,
        tgt_cls: str,
        src_idx: int,
        tgt_idx: int,
    ) -> z3.BoolRef:
        """Exact final trace semantics: holds iff at least one producer fires."""
        if self.trace_consumer_pairs is not None:
            if (src_cls, tgt_cls) not in self.trace_consumer_pairs:
                return z3.BoolVal(False)
            key = (src_cls, tgt_cls, self.layer_count, src_idx, tgt_idx)
            return self.trace_before_layer_vars.get(key, z3.BoolVal(False))
        key = (src_cls, tgt_cls, src_idx, tgt_idx)
        lits = [f for _, f in self.trace_producers.get(key, [])]
        if not lits:
            return z3.BoolVal(False)
        return z3.Or(lits)
    
    def _encode_all_rules(self):
        """Encode all rules in the transformation, or only relevant_rules if set."""
        for layer_idx, layer in enumerate(self.transformation.layers):
            for rule in layer.rules:
                if self.relevant_rules is not None and rule.id not in self.relevant_rules:
                    continue
                self._encode_rule(rule, layer_idx)
    
    def _encode_rule(self, rule: Rule, layer_idx: int):
        """Encode a single rule with appropriate firing semantics."""
        n_match = len(rule.match_elements)
        match_elem_names = {me.name for me in rule.match_elements}
        
        self.fires[rule.id] = {}
        self.element_bindings[rule.id] = {}
        
        has_backward_links = rule.has_backward_links
        bl_by_apply: Dict[ElementId, List[ElementId]] = defaultdict(list)
        for bl in rule.backward_links:
            bl_by_apply[bl.apply_element].append(bl.match_element)
        
        # Determine the case based on rule structure
        has_free_elements = self._has_free_match_elements(rule)
        has_attr_constraints = rule.guard is not None or any(
            me.where_clause is not None for me in rule.match_elements
        )
        
        # Enumerate all possible bindings of match elements to indices over the
        # full configured bound N. Enforce injectivity per type: same-type match
        # elements get distinct indices; different types may share an index (slots
        # are per-type, so e.g. Model at 0 and Package at 0 are distinct objects).
        match_domains = [
            range(self._source_bound_for(self._get_class_name(me.class_type)))
            for me in rule.match_elements
        ]
        all_bindings = [
            b for b in product(*match_domains)
            if _binding_injective_per_type(rule.match_elements, b, self._get_class_name)
        ]
        
        for binding in all_bindings:
            # Create element name -> index mapping
            elem_map: Dict[str, int] = {}
            elem_types: Dict[str, str] = {}  # element name -> class type
            
            for i, me in enumerate(rule.match_elements):
                elem_map[me.name] = binding[i]
                elem_map[me.id] = binding[i]
                cls_name = self._get_class_name(me.class_type)
                elem_types[me.name] = cls_name
                elem_types[str(me.id)] = cls_name
            
            backward_apply_ids = set(bl_by_apply.keys())

            # Backward-linked apply elements search explicitly over reusable target slots.
            # Newly created apply elements use explicit per-slot choice variables.
            created_apply_choices: Dict[ElementId, List[Tuple[int, z3.BoolRef]]] = {}
            backward_apply_choices: Dict[ElementId, List[Tuple[int, z3.BoolRef]]] = {}
            binding_str = "_".join(str(b) for b in binding)
            for ae in rule.apply_elements:
                ae_cls_name = self._get_class_name(ae.class_type)
                elem_types[ae.name] = ae_cls_name
                elem_types[str(ae.id)] = ae_cls_name
                cls_name = self._get_class_name(ae.class_type)
                if ae.id in backward_apply_ids:
                    slot_choices: List[Tuple[int, z3.BoolRef]] = []
                    for tgt_idx in range(self._target_bound_for(cls_name)):
                        choice_var = z3.Bool(
                            f"reuse_{rule.name}_{ae.name}_{binding_str}_{tgt_idx}"
                        )
                        slot_choices.append((tgt_idx, choice_var))
                    backward_apply_choices[ae.id] = slot_choices
                else:
                    slot_choices: List[Tuple[int, z3.BoolRef]] = []
                    for tgt_idx in range(self._target_bound_for(cls_name)):
                        choice_var = z3.Bool(
                            f"choose_{rule.name}_{ae.name}_{binding_str}_{tgt_idx}"
                        )
                        slot_choices.append((tgt_idx, choice_var))
                        self._register_created_target_assignment(cls_name, tgt_idx, choice_var)
                    created_apply_choices[ae.id] = slot_choices
            
            self.element_bindings[rule.id][binding] = elem_map
            
            # Create firing variable for this binding
            fires_var = z3.Bool(f"fires_{rule.name}_{binding_str}")
            self.fires[rule.id][binding] = fires_var
            
            # Build precondition: all match elements exist with correct types
            precond_parts = []
            for i, me in enumerate(rule.match_elements):
                idx = binding[i]
                cls_name = self._get_class_name(me.class_type)
                exists_vars = self.model.get_source_exists(cls_name)
                if exists_vars and idx < len(exists_vars):
                    precond_parts.append(exists_vars[idx])
            
            # Add match link constraints
            for ml in rule.match_links:
                src_elem = rule.match_element_by_id.get(ml.source)
                tgt_elem = rule.match_element_by_id.get(ml.target)
                if src_elem and tgt_elem:
                    src_idx = elem_map.get(src_elem.name, 0)
                    tgt_idx = elem_map.get(tgt_elem.name, 0)
                    # Get association name
                    assoc_name = self._get_assoc_name(ml.assoc_type)
                    rel = self.model.get_source_relation(assoc_name)
                    if rel and src_idx < len(rel) and tgt_idx < len(rel[0]):
                        precond_parts.append(rel[src_idx][tgt_idx])
            
            backward_precond_parts: List[z3.BoolRef] = []
            # Strict backward-link semantics:
            # - backward-linked apply elements must already exist
            # - required source->target traces must already hold
            # - reuse target is unique wrt required trace intersection
            if has_backward_links:
                for ae in rule.apply_elements:
                    if ae.id not in backward_apply_ids:
                        continue
                    tgt_cls = self._get_class_name(ae.class_type)
                    me_ids = bl_by_apply.get(ae.id, [])
                    choice_vars: List[z3.BoolRef] = []
                    for tgt_idx, choice_var in backward_apply_choices.get(ae.id, []):
                        candidate_parts: List[z3.BoolRef] = []
                        tgt_exists = self.model.get_target_exists(tgt_cls)
                        if tgt_exists and tgt_idx < len(tgt_exists):
                            candidate_parts.append(tgt_exists[tgt_idx])
                        for me_id in me_ids:
                            match_elem = rule.match_element_by_id.get(me_id)
                            if match_elem is None:
                                continue
                            src_idx = elem_map.get(match_elem.name, 0)
                            src_cls = self._get_class_name(match_elem.class_type)
                            candidate_parts.append(
                                self.trace_visible_before_layer(
                                    layer_idx, src_cls, tgt_cls, src_idx, tgt_idx
                                )
                            )
                        for binding in ae.attribute_bindings:
                            attr_name = binding.target.attribute
                            tgt_attr_vars = self.model.get_target_attr(tgt_cls, attr_name)
                            if not tgt_attr_vars or tgt_idx >= len(tgt_attr_vars):
                                continue
                            value_z3 = self._translate_expr(
                                binding.value, elem_map, elem_types, match_elem_names
                            )
                            if value_z3 is not None:
                                candidate_parts.append(tgt_attr_vars[tgt_idx] == value_z3)
                        tgt_n = self._target_bound_for(tgt_cls)
                        for other_idx in range(tgt_n):
                            if other_idx == tgt_idx:
                                continue
                            other_parts: List[z3.BoolRef] = []
                            for me_id in me_ids:
                                match_elem = rule.match_element_by_id.get(me_id)
                                if match_elem is None:
                                    continue
                                src_idx = elem_map.get(match_elem.name, 0)
                                src_cls = self._get_class_name(match_elem.class_type)
                                other_parts.append(
                                    self.trace_visible_before_layer(
                                        layer_idx, src_cls, tgt_cls, src_idx, other_idx
                                    )
                                )
                            if other_parts:
                                candidate_parts.append(z3.Not(z3.And(other_parts)))
                        candidate = z3.And(candidate_parts) if candidate_parts else z3.BoolVal(False)
                        self.solver.add(choice_var == candidate)
                        choice_vars.append(choice_var)
                    if choice_vars:
                        backward_precond_parts.append(z3.Or(choice_vars))
                        self.solver.add(z3.PbLe([(v, 1) for v in choice_vars], 1))

            all_precond = precond_parts + backward_precond_parts
            precondition = z3.And(all_precond) if all_precond else z3.BoolVal(True)

            # Determine firing semantics based on case
            # For property verification, we use MUST-fire semantics for deterministic
            # rules to ensure Z3 doesn't find trivial counterexamples where rules
            # simply don't fire.
            #
            # Key insight: Attribute constraints are part of the firing condition,
            # not just lazy checks. Rule MUST fire when all conditions are met.
            
            full_condition = precondition
            
            # Include attribute constraints in the firing condition
            attr_constraint_parts = []
            
            # Add where clauses from match elements
            for me in rule.match_elements:
                if me.where_clause is not None:
                    where_z3 = self._translate_expr(me.where_clause, elem_map, elem_types, match_elem_names)
                    if where_z3 is not None:
                        attr_constraint_parts.append(where_z3)
            
            # Add rule guard
            if rule.guard is not None:
                guard_z3 = self._translate_expr(rule.guard, elem_map, elem_types, match_elem_names)
                if guard_z3 is not None:
                    attr_constraint_parts.append(guard_z3)
            
            if attr_constraint_parts:
                attr_constraint = z3.And(attr_constraint_parts)
                full_condition = z3.And(full_condition, attr_constraint)

            # Rule MUST fire when all conditions are met
            self.solver.add(fires_var == full_condition)

            # Newly created apply elements choose exactly one target slot when the rule fires.
            created_apply_choices_by_class: Dict[str, List[List[Tuple[int, z3.BoolRef]]]] = defaultdict(list)
            for ae in rule.apply_elements:
                if ae.id in backward_apply_ids:
                    continue
                cls_name = self._get_class_name(ae.class_type)
                slot_choices = created_apply_choices.get(ae.id, [])
                if slot_choices:
                    choice_vars = [var for _, var in slot_choices]
                    self.solver.add(z3.Implies(fires_var, z3.Or(choice_vars)))
                    self.solver.add(z3.PbLe([(v, 1) for v in choice_vars], 1))
                    for choice_var in choice_vars:
                        self.solver.add(z3.Implies(choice_var, fires_var))
                    for tgt_idx, choice_var in slot_choices:
                        self._register_target_node_justifier(cls_name, tgt_idx, choice_var)
                    created_apply_choices_by_class[cls_name].append(slot_choices)

            # Distinct apply elements of the same target class from the same firing
            # must not choose the same created target slot.
            for slot_choice_lists in created_apply_choices_by_class.values():
                for i in range(len(slot_choice_lists)):
                    for j in range(i + 1, len(slot_choice_lists)):
                        left = {idx: var for idx, var in slot_choice_lists[i]}
                        right = {idx: var for idx, var in slot_choice_lists[j]}
                        for tgt_idx in set(left) & set(right):
                            self.solver.add(z3.Not(z3.And(left[tgt_idx], right[tgt_idx])))
            
            # Postcondition: when rule fires, create non-backward apply elements and traces.
            postcond_parts = []

            for ae in rule.apply_elements:
                if ae.id in backward_apply_ids:
                    # Backward-linked apply elements are reused, never created.
                    continue
                cls_name = self._get_class_name(ae.class_type)
                exists_vars = self.model.get_target_exists(cls_name)
                if not exists_vars:
                    continue
                for tgt_idx, choice_var in created_apply_choices.get(ae.id, []):
                    if tgt_idx < len(exists_vars):
                        postcond_parts.append(z3.Implies(choice_var, exists_vars[tgt_idx]))
            
            # Create apply links
            for al in rule.apply_links:
                src_elem = rule.apply_element_by_id.get(al.source)
                tgt_elem = rule.apply_element_by_id.get(al.target)
                if src_elem and tgt_elem:
                    assoc_name = self._get_assoc_name(al.assoc_type)
                    rel = self.model.get_target_relation(assoc_name)
                    if not rel:
                        continue
                    if src_elem.id in backward_apply_ids:
                        src_cases = backward_apply_choices.get(src_elem.id, [])
                    else:
                        src_cases = created_apply_choices.get(src_elem.id, [])
                    if tgt_elem.id in backward_apply_ids:
                        tgt_cases = backward_apply_choices.get(tgt_elem.id, [])
                    else:
                        tgt_cases = created_apply_choices.get(tgt_elem.id, [])
                    for src_idx, src_cond in src_cases:
                        if src_idx >= len(rel):
                            continue
                        for tgt_idx, tgt_cond in tgt_cases:
                            if tgt_idx < len(rel[0]):
                                link_justification = z3.And(src_cond, tgt_cond)
                                self._register_target_link_justifier(
                                    assoc_name,
                                    src_idx,
                                    tgt_idx,
                                    link_justification,
                                )
                                postcond_parts.append(
                                    z3.Implies(link_justification, rel[src_idx][tgt_idx])
                                )

            # Apply-side attribute bindings for newly created apply elements.
            for ae in rule.apply_elements:
                if ae.id in backward_apply_ids:
                    continue
                tgt_cls_name = self._get_class_name(ae.class_type)
                for binding in ae.attribute_bindings:
                    attr_name = binding.target.attribute
                    tgt_attr_vars = self.model.get_target_attr(tgt_cls_name, attr_name)
                    if not tgt_attr_vars:
                        continue
                    value_z3 = self._translate_expr(binding.value, elem_map, elem_types, match_elem_names)
                    if value_z3 is not None:
                        for tgt_idx, choice_var in created_apply_choices.get(ae.id, []):
                            if tgt_idx < len(tgt_attr_vars):
                                postcond_parts.append(
                                    z3.Implies(choice_var, tgt_attr_vars[tgt_idx] == value_z3)
                                )
            
            # Implicit cartesian traces for newly created apply elements:
            # every match element traces to every non-backward apply element.
            for ae in rule.apply_elements:
                if ae.id in backward_apply_ids:
                    continue
                tgt_cls = self._get_class_name(ae.class_type)
                for tgt_idx, choice_var in created_apply_choices.get(ae.id, []):
                    for me in rule.match_elements:
                        src_idx = elem_map.get(me.name, 0)
                        src_cls = self._get_class_name(me.class_type)
                        if (
                            self.prune_unconsumed_trace_producers
                            and self.trace_consumer_pairs is not None
                            and (src_cls, tgt_cls) not in self.trace_consumer_pairs
                        ):
                            continue
                        # Record producer provenance for layer-aware visibility checks.
                        self._register_trace_producer(
                            layer_idx, src_cls, tgt_cls, src_idx, tgt_idx, choice_var
                        )

            if postcond_parts:
                self.solver.add(z3.Implies(fires_var, z3.And(postcond_parts)))
            
            # Accumulate attribute constraints
            if rule.guard:
                guard_z3 = self._translate_expr(rule.guard, elem_map, elem_types, match_elem_names)
                if guard_z3 is not None:
                    self.theta_attr.append(z3.Implies(fires_var, guard_z3))
    
    def _get_class_name(self, cls_id) -> str:
        """Get class name from ClassId."""
        if isinstance(cls_id, str):
            return cls_id
        return str(cls_id)
    
    def _get_assoc_name(self, assoc_id) -> str:
        """Get association name from AssocId."""
        if isinstance(assoc_id, str):
            return assoc_id
        return str(assoc_id)
    
    def _has_free_match_elements(self, rule: Rule) -> bool:
        """Check if rule has match elements not constrained by backward links."""
        backward_match_elements = rule.backward_link_match_elements
        for me in rule.match_elements:
            if me.id not in backward_match_elements:
                return True
        return False
    
    def _translate_expr(
        self, 
        expr: Expr, 
        elem_map: Dict[str, int],
        elem_types: Optional[Dict[str, str]] = None,
        match_elem_names: Optional[Set[str]] = None
    ) -> Optional[z3.ExprRef]:
        """Translate a DSLTrans expression to Z3."""
        try:
            env = {}
            elem_types = elem_types or {}
            match_elem_names = match_elem_names or set()
            
            # Map element names to their indices
            for name, idx in elem_map.items():
                env[name] = z3.IntVal(idx)
            
            # Map attribute references to actual SMT variables
            for elem_name, idx in elem_map.items():
                # Get the class type for this element
                cls_name = elem_types.get(elem_name)
                if not cls_name:
                    continue
                
                if elem_name in match_elem_names:
                    # Find class in source metamodel and include inherited attributes
                    for cls in self.transformation.source_metamodel.classes:
                        if cls.name != cls_name:
                            continue
                        for attr in self.model._iter_effective_attributes(self.transformation.source_metamodel, cls):
                            attr_key = f"{elem_name}.{attr.name}"
                            attr_vars = self.model.get_source_attr(cls_name, attr.name)
                            if attr_vars and idx < len(attr_vars):
                                env[attr_key] = attr_vars[idx]
                        break
                else:
                    # Find class in target metamodel and include inherited attributes
                    for cls in self.transformation.target_metamodel.classes:
                        if cls.name != cls_name:
                            continue
                        for attr in self.model._iter_effective_attributes(self.transformation.target_metamodel, cls):
                            attr_key = f"{elem_name}.{attr.name}"
                            attr_vars = self.model.get_target_attr(cls_name, attr.name)
                            if attr_vars and idx < len(attr_vars):
                                env[attr_key] = attr_vars[idx]
                        break
            
            translator = ExprToZ3(env)
            return translator.translate(expr)
        except Exception as exc:
            self.model.encoding_issues.append(f"failed to encode expression {expr}: {exc}")
            return None
    
    def get_theta_attr(self) -> z3.BoolRef:
        """Get the accumulated attribute constraints."""
        if self.theta_attr:
            return z3.And(self.theta_attr)
        return z3.BoolVal(True)


# -----------------------------------------------------------------------------
# SMT Property Encoder
# -----------------------------------------------------------------------------

class SMTPropertyEncoder:
    """
    Encodes property verification via counterexample search.
    
    For property P = (Pre, Post):
      Add constraint: ∃ assignment where Pre holds AND Post doesn't hold
      If SAT -> VIOLATED (counterexample found)
      If UNSAT -> HOLDS (no counterexample exists)
    """
    
    def __init__(
        self,
        model_encoder: SMTModelEncoder,
        rule_encoder: SMTRuleEncoder,
        use_symmetry_breaking: bool = False,
    ):
        self.model = model_encoder
        self.rules = rule_encoder
        self.bound = model_encoder.bound
        self.use_symmetry_breaking = use_symmetry_breaking
        self.last_encoding_stats = PropertyEncodingStats()

    def _get_obligation_rule(self, prop: Property):
        """
        If the property precondition matches a single rule that must fire when pre holds
        (same structure, constraint-compatible, produces postcondition), return that rule.
        Used to avoid spurious counterexamples where the solver finds a short execution
        that omits the rule (e.g. abstract class + discriminator table).
        """
        pre = prop.precondition
        post = prop.postcondition
        if not pre or not pre.elements:
            return None
        pre_name_to_type = {me.name: str(me.class_type) for me in pre.elements}
        pre_by_id = {me.id: me for me in pre.elements}
        post_by_id = {ae.id: ae for ae in post.elements}
        pre_link_sig = {
            (str(link.assoc_type), pre_by_id[link.source].name, pre_by_id[link.target].name, str(link.kind))
            for link in pre.links
            if link.source in pre_by_id and link.target in pre_by_id
        }
        prop_attr = _property_attr_summary(prop)
        trans = self.rules.transformation
        candidates = []
        for rule in trans.all_rules:
            # Rules that reuse prior targets through backward links are not safe
            # obligation rules: their firing depends on earlier trace producers
            # that may be absent in mutated executions even when the property
            # precondition holds.
            if rule.backward_links:
                continue
            rule_name_to_type = {me.name: str(me.class_type) for me in rule.match_elements}
            if rule_name_to_type != pre_name_to_type:
                continue
            rule_match_sig = {
                (str(link.assoc_type), rule.match_element_by_id[link.source].name, rule.match_element_by_id[link.target].name, str(link.kind))
                for link in rule.match_links
                if link.source in rule.match_element_by_id and link.target in rule.match_element_by_id
            }
            if rule_match_sig != pre_link_sig:
                continue

            apply_by_name = {ae.name: ae for ae in rule.apply_elements}
            if any(
                ae.name not in apply_by_name
                or str(apply_by_name[ae.name].class_type) != str(ae.class_type)
                for ae in post.elements
            ):
                continue
            rule_link_sig = {
                (
                    str(link.assoc_type),
                    rule.apply_element_by_id[link.source].name,
                    rule.apply_element_by_id[link.target].name,
                )
                for link in rule.apply_links
                if link.source in rule.apply_element_by_id and link.target in rule.apply_element_by_id
            }
            post_link_sig = {
                (
                    str(link.assoc_type),
                    post_by_id[link.source].name,
                    post_by_id[link.target].name,
                )
                for link in post.links
                if link.source in post_by_id and link.target in post_by_id
            }
            if not post_link_sig.issubset(rule_link_sig):
                continue

            backward_by_apply_name: Dict[str, Set[str]] = defaultdict(set)
            for bl in rule.backward_links:
                apply_elem = rule.apply_element_by_id.get(bl.apply_element)
                match_elem = rule.match_element_by_id.get(bl.match_element)
                if apply_elem is None or match_elem is None:
                    continue
                backward_by_apply_name[apply_elem.name].add(match_elem.name)
            trace_topology_ok = True
            for post_elem_id, pre_elem_id in post.trace_links:
                post_elem = post_by_id.get(post_elem_id)
                pre_elem = pre_by_id.get(pre_elem_id)
                if post_elem is None or pre_elem is None:
                    trace_topology_ok = False
                    break
                rule_apply = apply_by_name.get(post_elem.name)
                if rule_apply is None:
                    trace_topology_ok = False
                    break
                backward_sources = backward_by_apply_name.get(post_elem.name, set())
                if backward_sources:
                    if pre_elem.name not in backward_sources:
                        trace_topology_ok = False
                        break
                elif pre_elem.name not in rule_name_to_type:
                    trace_topology_ok = False
                    break
            if not trace_topology_ok:
                continue

            rule_attr = _rule_attr_summary(rule)
            if not _merge_constraint_compat(rule_attr.constraints, prop_attr.constraints):
                continue
            candidates.append(rule)
        if len(candidates) != 1:
            return None
        return candidates[0]

    def _domains_for_elements(self, elements, *, source_side: bool) -> List[range]:
        domains: List[range] = []
        for e in elements:
            cls_name = self._get_class_name(e.class_type)
            n = (
                self.model.source_bound_for(cls_name)
                if source_side
                else self.model.target_bound_for(cls_name)
            )
            domains.append(range(n))
        return domains

    @staticmethod
    def _encode_symbolic_choice(
        selector: z3.ArithRef,
        choices: List[z3.BoolRef],
    ) -> z3.BoolRef:
        if not choices:
            return z3.BoolVal(False)
        return z3.Or(
            [z3.And(selector == i, choice) for i, choice in enumerate(choices)]
        )

    @staticmethod
    def _encode_symbolic_matrix_choice(
        row_selector: z3.ArithRef,
        col_selector: z3.ArithRef,
        matrix: List[List[z3.BoolRef]],
    ) -> z3.BoolRef:
        if not matrix or not matrix[0]:
            return z3.BoolVal(False)
        parts = []
        for i, row in enumerate(matrix):
            for j, cell in enumerate(row):
                parts.append(z3.And(row_selector == i, col_selector == j, cell))
        return z3.Or(parts) if parts else z3.BoolVal(False)

    @staticmethod
    def _should_use_symbolic_connected_post(
        post: PostCondition,
        factored_groups: list[list],
    ) -> bool:
        return (
            post.constraint is None
            and len(post.elements) >= 4
            and len(factored_groups) <= 1
        )

    def _encode_symbolic_postcondition(
        self,
        post: PostCondition,
        pre_elem_map: Dict[str, int],
        pre_elem_types: Dict[str, str],
        selector_tag: str,
    ) -> z3.BoolRef:
        del selector_tag
        domain_sizes: Dict[object, int] = {}
        elems_by_id = {e.id: e for e in post.elements}
        for ae in post.elements:
            cls_name = self._get_class_name(ae.class_type)
            exists_vars = self.model.get_target_exists(cls_name)
            domain_sizes[ae.id] = len(exists_vars) if exists_vars else self.model.target_bound_for(cls_name)

        factors: List[tuple[tuple[object, ...], Dict[tuple[int, ...], z3.BoolRef]]] = []

        for ae in post.elements:
            cls_name = self._get_class_name(ae.class_type)
            exists_vars = self.model.get_target_exists(cls_name)
            if exists_vars:
                factors.append(
                    (
                        (ae.id,),
                        {
                            (idx,): exists_vars[idx]
                            for idx in range(domain_sizes[ae.id])
                        },
                    )
                )

        for post_elem_id, pre_elem_id in post.trace_links:
            post_elem = elems_by_id.get(post_elem_id)
            pre_elem_name = str(pre_elem_id)
            if post_elem is None or pre_elem_name not in pre_elem_map:
                continue
            src_cls = pre_elem_types.get(pre_elem_name)
            tgt_cls = self._get_class_name(post_elem.class_type)
            if src_cls is None or tgt_cls is None:
                continue
            pre_idx = pre_elem_map[pre_elem_name]
            factors.append(
                (
                    (post_elem.id,),
                    {
                        (tgt_idx,): self.rules.trace_holds(src_cls, tgt_cls, pre_idx, tgt_idx)
                        for tgt_idx in range(domain_sizes[post_elem.id])
                    },
                )
            )

        for link in post.links:
            src_elem = elems_by_id.get(link.source)
            tgt_elem = elems_by_id.get(link.target)
            if src_elem is None or tgt_elem is None:
                continue
            rel = self.model.get_target_relation(self._get_assoc_name(link.assoc_type))
            if rel is None:
                continue
            table: Dict[tuple[int, ...], z3.BoolRef] = {}
            for src_idx in range(domain_sizes[src_elem.id]):
                for tgt_idx in range(domain_sizes[tgt_elem.id]):
                    table[(src_idx, tgt_idx)] = rel[src_idx][tgt_idx]
            factors.append(((src_elem.id, tgt_elem.id), table))

        elems_by_class: Dict[str, List[ApplyElement]] = defaultdict(list)
        for ae in post.elements:
            elems_by_class[self._get_class_name(ae.class_type)].append(ae)
        for class_elems in elems_by_class.values():
            for i in range(len(class_elems)):
                for j in range(i + 1, len(class_elems)):
                    left = class_elems[i]
                    right = class_elems[j]
                    table: Dict[tuple[int, ...], z3.BoolRef] = {}
                    for left_idx in range(domain_sizes[left.id]):
                        for right_idx in range(domain_sizes[right.id]):
                            table[(left_idx, right_idx)] = z3.BoolVal(left_idx != right_idx)
                    factors.append(((left.id, right.id), table))

        adjacency: Dict[object, Set[object]] = {ae.id: set() for ae in post.elements}
        for _scope, _table in factors:
            for i in range(len(_scope)):
                for j in range(i + 1, len(_scope)):
                    adjacency[_scope[i]].add(_scope[j])
                    adjacency[_scope[j]].add(_scope[i])

        remaining = set(adjacency)
        elimination_order: List[object] = []
        while remaining:
            candidate = min(
                remaining,
                key=lambda var: (
                    len(adjacency[var] & remaining),
                    domain_sizes[var],
                    str(var),
                ),
            )
            elimination_order.append(candidate)
            neighbors = list(adjacency[candidate] & remaining)
            for i in range(len(neighbors)):
                for j in range(i + 1, len(neighbors)):
                    adjacency[neighbors[i]].add(neighbors[j])
                    adjacency[neighbors[j]].add(neighbors[i])
            remaining.remove(candidate)

        active_factors = list(factors)
        for var in elimination_order:
            bucket = [factor for factor in active_factors if var in factor[0]]
            if not bucket:
                continue
            active_factors = [factor for factor in active_factors if var not in factor[0]]
            new_scope = tuple(
                key
                for key in dict.fromkeys(
                    elem_id
                    for scope, _ in bucket
                    for elem_id in scope
                    if elem_id != var
                )
            )
            table: Dict[tuple[int, ...], z3.BoolRef] = {}
            other_ranges = [range(domain_sizes[scope_var]) for scope_var in new_scope]
            for other_assignment in product(*other_ranges) if other_ranges else [()]:
                disjuncts: List[z3.BoolRef] = []
                assignment_map = {
                    scope_var: value
                    for scope_var, value in zip(new_scope, other_assignment)
                }
                for value in range(domain_sizes[var]):
                    assignment_map[var] = value
                    conjuncts: List[z3.BoolRef] = []
                    for scope, factor_table in bucket:
                        key = tuple(assignment_map[scope_var] for scope_var in scope)
                        conjuncts.append(factor_table[key])
                    disjuncts.append(z3.And(conjuncts) if conjuncts else z3.BoolVal(True))
                table[other_assignment] = z3.Or(disjuncts) if disjuncts else z3.BoolVal(False)
            active_factors.append((new_scope, table))

        scalar_factors = [table[()] for scope, table in active_factors if not scope]
        return z3.And(scalar_factors) if scalar_factors else z3.BoolVal(True)
    
    def encode_property(self, prop: Property, solver: z3.Solver) -> z3.BoolRef:
        """
        Encode a property as a counterexample search.
        
        Returns a constraint that is SAT iff the property is violated.
        """
        stats = PropertyEncodingStats()
        violations = []
        
        # Determine number of elements in precondition
        pre = prop.precondition
        post = prop.postcondition
        
        n_pre = len(pre.elements) if pre else 0
        n_post = len(post.elements)
        
        # Build element name to class type mapping for precondition
        pre_elem_types: Dict[str, str] = {}
        if pre:
            for me in pre.elements:
                cls_name = self._get_class_name(me.class_type)
                pre_elem_types[me.name] = cls_name
                pre_elem_types[str(me.id)] = cls_name
        
        # Generate bindings for precondition: injective per type (same-type elements distinct).
        pre_bindings = (
            [
                b for b in product(*self._domains_for_elements(pre.elements, source_side=True))
                if _binding_injective_per_type(pre.elements, b, self._get_class_name)
            ]
            if n_pre > 0
            else [()]
        )
        stats.pre_bindings = len(pre_bindings)
        
        # Compute postcondition connected components for factored encoding.
        # Elements connected by links or shared trace-link targets are in the same component.
        # Postcondition-level constraints can relate arbitrary post elements, so fall back
        # to full post-binding enumeration when a global post constraint is present.
        post_components = self._postcondition_components(post)
        stats.post_components = len(post_components)
        factored_groups = self._factored_postcondition_groups(
            post,
            post_components,
            pre_elem_types,
        )
        use_factored_post = post.constraint is None and len(factored_groups) > 1
        use_symbolic_connected_post = self._should_use_symbolic_connected_post(
            post,
            factored_groups,
        )
        stats.used_factored_post = use_factored_post
        if not use_factored_post:
            post_components = []
        else:
            post_components = factored_groups
        obligation_rule = self._get_obligation_rule(prop)
        
        for pre_idx, pre_binding in enumerate(pre_bindings):
            # Build element map for precondition
            pre_elem_map: Dict[str, int] = {}
            if pre:
                for i, me in enumerate(pre.elements):
                    pre_elem_map[me.name] = pre_binding[i]
                    pre_elem_map[str(me.id)] = pre_binding[i]
            
            # Check if precondition holds (including where clauses!)
            pre_holds = self._encode_precondition(pre, pre_elem_map, pre_elem_types)
            
            if use_factored_post:
                # Factored postcondition: each connected component is quantified independently.
                # post_satisfied = AND(component_i_satisfied for each component i)
                component_parts = []
                for comp_elems in post_components:
                    symmetry_groups = self._component_symmetry_groups(post, comp_elems)
                    comp_bindings = [
                        b for b in product(*self._domains_for_elements(comp_elems, source_side=False))
                        if _binding_injective_per_type(comp_elems, b, self._get_class_name)
                        and self._binding_respects_symmetry(comp_elems, b, symmetry_groups)
                    ]
                    stats.post_component_bindings += len(comp_bindings)
                    comp_holds_any = []
                    for comp_binding in comp_bindings:
                        post_elem_map = dict(pre_elem_map)
                        for j, ae in enumerate(comp_elems):
                            post_elem_map[ae.name] = comp_binding[j]
                            post_elem_map[str(ae.id)] = comp_binding[j]
                        # Encode only the constraints relevant to this component's elements
                        post_constraint = self._encode_postcondition_component(
                            post, comp_elems, post_elem_map, pre_elem_map, pre_elem_types,
                        )
                        comp_holds_any.append(post_constraint)
                    component_parts.append(
                        z3.Or(comp_holds_any) if comp_holds_any else z3.BoolVal(False)
                    )
                post_satisfied = z3.And(component_parts) if component_parts else z3.BoolVal(False)
            elif use_symbolic_connected_post:
                post_satisfied = self._encode_symbolic_postcondition(
                    post,
                    pre_elem_map,
                    pre_elem_types,
                    selector_tag=f"{prop.id}_mono_{pre_idx}",
                )
            else:
                full_bindings = [
                    b for b in product(*self._domains_for_elements(post.elements, source_side=False))
                    if _binding_injective_per_type(post.elements, b, self._get_class_name)
                ]
                stats.post_full_bindings += len(full_bindings)
                full_holds_any = []
                for post_binding in full_bindings:
                    post_elem_map = dict(pre_elem_map)
                    for j, ae in enumerate(post.elements):
                        post_elem_map[ae.name] = post_binding[j]
                        post_elem_map[str(ae.id)] = post_binding[j]
                    full_holds_any.append(
                        self._encode_postcondition(
                            post,
                            post_elem_map,
                            pre_elem_map,
                            pre_elem_types,
                        )
                    )
                post_satisfied = z3.Or(full_holds_any) if full_holds_any else z3.BoolVal(False)
            
            # Violation: pre holds AND post doesn't (for any binding).
            # When an obligation rule exists (pre matches a single rule that produces post),
            # restrict to executions where that rule did fire. Otherwise we would
            # admit spurious counterexamples that only arise by omitting the unique
            # producer from the execution.
            violation = None
            if pre_holds is not None:
                violation = z3.And(pre_holds, z3.Not(post_satisfied))
            else:
                violation = z3.Not(post_satisfied)
            if obligation_rule and violation is not None:
                rule_binding = tuple(
                    pre_elem_map[me.name] for me in obligation_rule.match_elements
                )
                fires_var = self.rules.fires.get(obligation_rule.id, {}).get(rule_binding)
                if fires_var is not None:
                    violation = z3.And(violation, fires_var)
            violations.append(violation)
        stats.violation_count = len(violations)
        self.last_encoding_stats = stats
        
        # Include theta_attr in the check
        theta = self.rules.get_theta_attr()
        
        if violations:
            return z3.And(theta, z3.Or(violations))
        return z3.BoolVal(False)
    
    def encode_property_violation_list(
        self, prop: Property
    ) -> Tuple[Optional[z3.BoolRef], List[z3.BoolRef]]:
        """
        Encode property as a list of violation constraints (one per pre-binding).
        Uses factored postcondition encoding (same as encode_property).
        Returns (theta_attr, [v0, v1, ...]) so the verifier can check each vi
        incrementally (push, add theta and vi, check, pop) for smaller per-check formulas.
        """
        stats = PropertyEncodingStats()
        pre = prop.precondition
        post = prop.postcondition
        n_pre = len(pre.elements) if pre else 0
        pre_elem_types: Dict[str, str] = {}
        if pre:
            for me in pre.elements:
                cls_name = self._get_class_name(me.class_type)
                pre_elem_types[me.name] = cls_name
                pre_elem_types[str(me.id)] = cls_name
        pre_bindings = (
            [
                b for b in product(*self._domains_for_elements(pre.elements, source_side=True))
                if _binding_injective_per_type(pre.elements, b, self._get_class_name)
            ]
            if n_pre > 0
            else [()]
        )
        stats.pre_bindings = len(pre_bindings)
        post_components = self._postcondition_components(post)
        stats.post_components = len(post_components)
        factored_groups = self._factored_postcondition_groups(
            post,
            post_components,
            pre_elem_types,
        )
        use_factored_post = post.constraint is None and len(factored_groups) > 1
        use_symbolic_connected_post = self._should_use_symbolic_connected_post(
            post,
            factored_groups,
        )
        stats.used_factored_post = use_factored_post
        if not use_factored_post:
            post_components = []
        else:
            post_components = factored_groups
        obligation_rule = self._get_obligation_rule(prop)
        violations: List[z3.BoolRef] = []
        for pre_idx, pre_binding in enumerate(pre_bindings):
            pre_elem_map: Dict[str, int] = {}
            if pre:
                for i, me in enumerate(pre.elements):
                    pre_elem_map[me.name] = pre_binding[i]
                    pre_elem_map[str(me.id)] = pre_binding[i]
            pre_holds = self._encode_precondition(pre, pre_elem_map, pre_elem_types)
            if use_factored_post:
                component_parts = []
                for comp_elems in post_components:
                    symmetry_groups = self._component_symmetry_groups(post, comp_elems)
                    comp_bindings = [
                        b for b in product(*self._domains_for_elements(comp_elems, source_side=False))
                        if _binding_injective_per_type(comp_elems, b, self._get_class_name)
                        and self._binding_respects_symmetry(comp_elems, b, symmetry_groups)
                    ]
                    stats.post_component_bindings += len(comp_bindings)
                    comp_holds_any = []
                    for comp_binding in comp_bindings:
                        post_elem_map = dict(pre_elem_map)
                        for j, ae in enumerate(comp_elems):
                            post_elem_map[ae.name] = comp_binding[j]
                            post_elem_map[str(ae.id)] = comp_binding[j]
                        post_constraint = self._encode_postcondition_component(
                            post, comp_elems, post_elem_map, pre_elem_map, pre_elem_types,
                        )
                        comp_holds_any.append(post_constraint)
                    component_parts.append(
                        z3.Or(comp_holds_any) if comp_holds_any else z3.BoolVal(False)
                    )
                post_satisfied = z3.And(component_parts) if component_parts else z3.BoolVal(False)
            elif use_symbolic_connected_post:
                post_satisfied = self._encode_symbolic_postcondition(
                    post,
                    pre_elem_map,
                    pre_elem_types,
                    selector_tag=f"{prop.id}_inc_{pre_idx}",
                )
            else:
                full_bindings = [
                    b for b in product(*self._domains_for_elements(post.elements, source_side=False))
                    if _binding_injective_per_type(post.elements, b, self._get_class_name)
                ]
                stats.post_full_bindings += len(full_bindings)
                full_holds_any = []
                for post_binding in full_bindings:
                    post_elem_map = dict(pre_elem_map)
                    for j, ae in enumerate(post.elements):
                        post_elem_map[ae.name] = post_binding[j]
                        post_elem_map[str(ae.id)] = post_binding[j]
                    full_holds_any.append(
                        self._encode_postcondition(
                            post,
                            post_elem_map,
                            pre_elem_map,
                            pre_elem_types,
                        )
                    )
                post_satisfied = z3.Or(full_holds_any) if full_holds_any else z3.BoolVal(False)
            violation = (
                z3.And(pre_holds, z3.Not(post_satisfied))
                if pre_holds is not None
                else z3.Not(post_satisfied)
            )
            if obligation_rule:
                rule_binding = tuple(
                    pre_elem_map[me.name] for me in obligation_rule.match_elements
                )
                fires_var = self.rules.fires.get(obligation_rule.id, {}).get(rule_binding)
                if fires_var is not None:
                    violation = z3.And(violation, fires_var)
            violations.append(violation)
        stats.violation_count = len(violations)
        self.last_encoding_stats = stats
        theta = self.rules.get_theta_attr()
        return (theta, violations)
    
    def _encode_precondition(
        self,
        pre: Optional[PreCondition],
        elem_map: Dict[str, int],
        elem_types: Optional[Dict[str, str]] = None
    ) -> Optional[z3.BoolRef]:
        """Encode precondition pattern including where clauses."""
        if pre is None or not pre.elements:
            return None
        
        parts = []
        elem_types = elem_types or {}
        
        # Build elem_types if not provided
        if not elem_types:
            for me in pre.elements:
                cls_name = self._get_class_name(me.class_type)
                elem_types[me.name] = cls_name
                elem_types[str(me.id)] = cls_name
        
        # Element existence
        for me in pre.elements:
            idx = elem_map.get(me.name, 0)
            cls_name = self._get_class_name(me.class_type)
            exists_vars = self.model.get_source_exists(cls_name)
            if exists_vars and idx < len(exists_vars):
                parts.append(exists_vars[idx])
            
            # CRITICAL: Include where clause constraints
            if me.where_clause is not None:
                where_z3 = self._translate_precondition_expr(me.where_clause, elem_map, elem_types)
                if where_z3 is not None:
                    parts.append(where_z3)
        
        # Link constraints
        for link in pre.links:
            src_elem = next((e for e in pre.elements if e.id == link.source), None)
            tgt_elem = next((e for e in pre.elements if e.id == link.target), None)
            if src_elem and tgt_elem:
                src_idx = elem_map.get(src_elem.name, 0)
                tgt_idx = elem_map.get(tgt_elem.name, 0)
                assoc_name = self._get_assoc_name(link.assoc_type)
                rel = self.model.get_source_relation(assoc_name)
                if rel and src_idx < len(rel) and tgt_idx < len(rel[0]):
                    parts.append(rel[src_idx][tgt_idx])

        if pre.constraint is not None:
            constraint_z3 = self._translate_property_expr(
                pre.constraint,
                elem_map,
                elem_types,
                source_side=True,
            )
            if constraint_z3 is not None:
                parts.append(constraint_z3)
        
        if parts:
            return z3.And(parts)
        return z3.BoolVal(True)
    
    def _translate_property_expr(
        self,
        expr: Expr,
        elem_map: Dict[str, int],
        elem_types: Dict[str, str],
        *,
        source_side: bool,
    ) -> Optional[z3.ExprRef]:
        """Translate a property expression against the source or target model."""
        try:
            env = {}
            mm = self.model.source_mm if source_side else self.model.target_mm
            
            # Map element names to their indices
            for name, idx in elem_map.items():
                env[name] = z3.IntVal(idx)
            
            # Map attribute references to actual SMT variables from the selected metamodel.
            for elem_name, idx in elem_map.items():
                cls_name = elem_types.get(elem_name)
                if not cls_name:
                    continue
                
                for cls in mm.classes:
                    if cls.name != cls_name:
                        continue
                    for attr in self.model._iter_effective_attributes(mm, cls):
                        attr_key = f"{elem_name}.{attr.name}"
                        attr_vars = (
                            self.model.get_source_attr(cls_name, attr.name)
                            if source_side
                            else self.model.get_target_attr(cls_name, attr.name)
                        )
                        if attr_vars and idx < len(attr_vars):
                            env[attr_key] = attr_vars[idx]
                    break
            
            translator = ExprToZ3(env)
            return translator.translate(expr)
        except Exception as exc:
            side = "precondition" if source_side else "postcondition"
            self.model.encoding_issues.append(
                f"failed to encode {side} expression {expr}: {exc}"
            )
            return None

    def _translate_precondition_expr(
        self,
        expr: Expr,
        elem_map: Dict[str, int],
        elem_types: Dict[str, str]
    ) -> Optional[z3.ExprRef]:
        """Translate a precondition expression (uses source metamodel)."""
        return self._translate_property_expr(
            expr,
            elem_map,
            elem_types,
            source_side=True,
        )
    
    @staticmethod
    def _postcondition_components(post: PostCondition) -> list[list]:
        """Partition postcondition elements into connected components.

        Two elements are connected if they share a link or are trace-linked
        to the same pre-element.  Independent elements get separate components,
        enabling factored (per-component) existential quantification.
        """
        elems = list(post.elements)
        id_to_idx = {e.id: i for i, e in enumerate(elems)}
        parent = list(range(len(elems)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Connect elements linked by postcondition links
        for link in post.links:
            a = id_to_idx.get(link.source)
            b = id_to_idx.get(link.target)
            if a is not None and b is not None:
                union(a, b)

        # Connect elements that trace to the SAME pre-element
        pre_to_post: Dict[str, list[int]] = {}
        for post_id, pre_id in post.trace_links:
            idx = id_to_idx.get(post_id)
            if idx is not None:
                pre_to_post.setdefault(str(pre_id), []).append(idx)
        for indices in pre_to_post.values():
            for k in range(1, len(indices)):
                union(indices[0], indices[k])

        # Build components
        comp_map: Dict[int, list] = {}
        for i, e in enumerate(elems):
            comp_map.setdefault(find(i), []).append(e)
        return list(comp_map.values())

    def _factored_postcondition_groups(
        self,
        post: PostCondition,
        components: list[list],
        pre_elem_types: Dict[str, str],
    ) -> list[list]:
        """
        Merge disconnected postcondition components into exact factor groups.

        Base components are disconnected wrt post links and shared traced
        pre-elements. They can still need joint quantification when some
        same-class post elements from different components could alias on the
        same target slot, because global same-type injectivity must then be
        preserved across those components.

        We therefore union components only when there is an exact potential
        aliasing dependency between them, and factor at the granularity of
        those dependency groups.
        """
        if len(components) <= 1:
            return components

        trace_demands = self._post_element_trace_demands(post, pre_elem_types)
        producer_caps = self._trace_producer_capabilities_by_target_class()
        parent = list(range(len(components)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for left_idx in range(len(components)):
            for right_idx in range(left_idx + 1, len(components)):
                if self._components_may_alias(
                    components[left_idx],
                    components[right_idx],
                    trace_demands,
                    producer_caps,
                ):
                    union(left_idx, right_idx)

        grouped: Dict[int, list] = {}
        for comp_idx, comp in enumerate(components):
            grouped.setdefault(find(comp_idx), []).extend(comp)
        return list(grouped.values())

    def _components_may_alias(
        self,
        left_comp: list,
        right_comp: list,
        trace_demands: Dict[object, Counter],
        producer_caps: Dict[str, list[Counter]],
    ) -> bool:
        """Return whether two disconnected components may share a target slot."""
        left_by_class: Dict[str, list] = defaultdict(list)
        right_by_class: Dict[str, list] = defaultdict(list)
        for elem in left_comp:
            left_by_class[self._get_class_name(elem.class_type)].append(elem)
        for elem in right_comp:
            right_by_class[self._get_class_name(elem.class_type)].append(elem)

        shared_classes = set(left_by_class) & set(right_by_class)
        for cls_name in shared_classes:
            for left_elem in left_by_class[cls_name]:
                for right_elem in right_by_class[cls_name]:
                    if self._post_elements_may_alias(
                        left_elem,
                        right_elem,
                        trace_demands,
                        producer_caps,
                    ):
                        return True
        return False

    def _post_elements_may_alias(
        self,
        left_elem,
        right_elem,
        trace_demands: Dict[object, Counter],
        producer_caps: Dict[str, list[Counter]],
    ) -> bool:
        """
        Conservative exact alias test for same-class post elements.

        If either element is not trace-constrained, aliasing is always possible:
        existence alone does not distinguish target slots. Otherwise, aliasing
        requires a single creator of that target class whose trace supply can
        cover the combined trace demands of both post elements.
        """
        if self._get_class_name(left_elem.class_type) != self._get_class_name(right_elem.class_type):
            return False

        left_demand = trace_demands.get(left_elem.id, Counter())
        right_demand = trace_demands.get(right_elem.id, Counter())
        if not left_demand or not right_demand:
            return True

        needed = left_demand + right_demand
        target_cls = self._get_class_name(left_elem.class_type)
        for cap in producer_caps.get(target_cls, []):
            if all(cap.get(src_cls, 0) >= required for src_cls, required in needed.items()):
                return True
        return False

    def _post_element_trace_demands(
        self,
        post: PostCondition,
        pre_elem_types: Dict[str, str],
    ) -> Dict[object, Counter]:
        """Count required source trace classes for each post element."""
        demands: Dict[object, Counter] = defaultdict(Counter)
        for post_elem_id, pre_elem_id in post.trace_links:
            pre_elem_name = str(pre_elem_id)
            src_cls = pre_elem_types.get(pre_elem_name)
            if src_cls is not None:
                demands[post_elem_id][src_cls] += 1
        return demands

    def _trace_producer_capabilities_by_target_class(self) -> Dict[str, list[Counter]]:
        """Summarize which source-class multisets can trace to each target class."""
        capabilities: Dict[str, list[Counter]] = defaultdict(list)
        for rule in self.rules.transformation.all_rules:
            match_counts = Counter(
                self._get_class_name(match_elem.class_type)
                for match_elem in rule.match_elements
            )
            backward_apply_ids = {bl.apply_element for bl in rule.backward_links}
            for apply_elem in rule.apply_elements:
                if apply_elem.id in backward_apply_ids:
                    continue
                target_cls = self._get_class_name(apply_elem.class_type)
                capabilities[target_cls].append(match_counts)
        return capabilities


    def _component_symmetry_groups(self, post: PostCondition, comp_elems: list) -> list[list[int]]:
        """
        Return groups of interchangeable post elements for safe symmetry breaking.

        Safety criterion (conservative):
        - same target class
        - no incident post links within the full postcondition
        - same set of traced pre-elements
        """
        if not self.use_symmetry_breaking or len(comp_elems) <= 1:
            return []
        comp_id_to_pos = {e.id: i for i, e in enumerate(comp_elems)}
        incident: dict[object, int] = {e.id: 0 for e in comp_elems}
        for link in post.links:
            if link.source in incident:
                incident[link.source] += 1
            if link.target in incident:
                incident[link.target] += 1
        trace_pre: dict[object, tuple[str, ...]] = {e.id: tuple() for e in comp_elems}
        tmp: dict[object, list[str]] = {e.id: [] for e in comp_elems}
        for post_id, pre_id in post.trace_links:
            if post_id in tmp:
                tmp[post_id].append(str(pre_id))
        for eid, arr in tmp.items():
            trace_pre[eid] = tuple(sorted(arr))

        by_sig: Dict[tuple[str, int, tuple[str, ...]], list[int]] = {}
        for e in comp_elems:
            sig = (
                self._get_class_name(e.class_type),
                incident[e.id],
                trace_pre[e.id],
            )
            by_sig.setdefault(sig, []).append(comp_id_to_pos[e.id])
        groups = []
        for (_sig, positions) in by_sig.items():
            # Only break when all elements are isolated wrt post links.
            if len(positions) >= 2:
                sample_elem = comp_elems[positions[0]]
                if incident[sample_elem.id] == 0:
                    groups.append(sorted(positions))
        return groups

    @staticmethod
    def _binding_respects_symmetry(comp_elems: list, binding: tuple[int, ...], groups: list[list[int]]) -> bool:
        """Canonicalize bindings by requiring ascending indices inside each symmetry group."""
        if not groups:
            return True
        for g in groups:
            prev = None
            for pos in g:
                cur = binding[pos]
                if prev is not None and prev >= cur:
                    return False
                prev = cur
        return True

    def _encode_postcondition_component(
        self,
        post: PostCondition,
        comp_elems: list,
        post_elem_map: Dict[str, int],
        pre_elem_map: Dict[str, int],
        pre_elem_types: Dict[str, str] = None,
    ) -> z3.BoolRef:
        """Encode constraints for a single postcondition component."""
        parts = []
        pre_elem_types = pre_elem_types or {}
        comp_ids = {e.id for e in comp_elems}

        # Element existence (only for elements in this component)
        for ae in comp_elems:
            idx = post_elem_map.get(ae.name, 0)
            cls_name = self._get_class_name(ae.class_type)
            exists_vars = self.model.get_target_exists(cls_name)
            if exists_vars and idx < len(exists_vars):
                parts.append(exists_vars[idx])

        # Links where BOTH endpoints are in this component
        for link in post.links:
            if link.source in comp_ids and link.target in comp_ids:
                src_elem = next((e for e in comp_elems if e.id == link.source), None)
                tgt_elem = next((e for e in comp_elems if e.id == link.target), None)
                if src_elem and tgt_elem:
                    src_idx = post_elem_map.get(src_elem.name, 0)
                    tgt_idx = post_elem_map.get(tgt_elem.name, 0)
                    assoc_name = self._get_assoc_name(link.assoc_type)
                    rel = self.model.get_target_relation(assoc_name)
                    if rel and src_idx < len(rel) and tgt_idx < len(rel[0]):
                        parts.append(rel[src_idx][tgt_idx])

        # Trace links where the post element is in this component
        for post_elem_id, pre_elem_id in post.trace_links:
            if post_elem_id not in comp_ids:
                continue
            post_elem = next((e for e in comp_elems if e.id == post_elem_id), None)
            pre_elem_name = str(pre_elem_id)
            if post_elem and pre_elem_name in pre_elem_map:
                post_idx = post_elem_map.get(post_elem.name, 0)
                pre_idx = pre_elem_map.get(pre_elem_name, 0)
                src_cls = pre_elem_types.get(pre_elem_name)
                tgt_cls = self._get_class_name(post_elem.class_type)
                if src_cls and tgt_cls:
                    parts.append(self.rules.trace_holds(src_cls, tgt_cls, pre_idx, post_idx))

        if parts:
            return z3.And(parts)
        return z3.BoolVal(True)

    def _encode_postcondition(
        self,
        post: PostCondition,
        post_elem_map: Dict[str, int],
        pre_elem_map: Dict[str, int],
        pre_elem_types: Dict[str, str] = None
    ) -> z3.BoolRef:
        """Encode postcondition pattern."""
        parts = []
        pre_elem_types = pre_elem_types or {}
        
        # Element existence
        for ae in post.elements:
            idx = post_elem_map.get(ae.name, 0)
            cls_name = self._get_class_name(ae.class_type)
            exists_vars = self.model.get_target_exists(cls_name)
            if exists_vars and idx < len(exists_vars):
                parts.append(exists_vars[idx])
        
        # Link constraints
        for link in post.links:
            src_elem = next((e for e in post.elements if e.id == link.source), None)
            tgt_elem = next((e for e in post.elements if e.id == link.target), None)
            if src_elem and tgt_elem:
                src_idx = post_elem_map.get(src_elem.name, 0)
                tgt_idx = post_elem_map.get(tgt_elem.name, 0)
                assoc_name = self._get_assoc_name(link.assoc_type)
                rel = self.model.get_target_relation(assoc_name)
                if rel and src_idx < len(rel) and tgt_idx < len(rel[0]):
                    parts.append(rel[src_idx][tgt_idx])
        
        # Trace link constraints
        for post_elem_id, pre_elem_id in post.trace_links:
            post_elem = next((e for e in post.elements if e.id == post_elem_id), None)
            pre_elem_name = str(pre_elem_id)
            
            if post_elem and pre_elem_name in pre_elem_map:
                post_idx = post_elem_map.get(post_elem.name, 0)
                pre_idx = pre_elem_map.get(pre_elem_name, 0)
                
                # Get source class from the pre_elem_types mapping
                src_cls = pre_elem_types.get(pre_elem_name)
                tgt_cls = self._get_class_name(post_elem.class_type)
                
                if src_cls and tgt_cls:
                    parts.append(self.rules.trace_holds(src_cls, tgt_cls, pre_idx, post_idx))

        if post.constraint is not None:
            post_elem_types: Dict[str, str] = {}
            for ae in post.elements:
                cls_name = self._get_class_name(ae.class_type)
                post_elem_types[ae.name] = cls_name
                post_elem_types[str(ae.id)] = cls_name
            constraint_z3 = self._translate_property_expr(
                post.constraint,
                post_elem_map,
                post_elem_types,
                source_side=False,
            )
            if constraint_z3 is not None:
                parts.append(constraint_z3)
        
        if parts:
            return z3.And(parts)
        return z3.BoolVal(True)
    
    def _get_class_name(self, cls_id) -> str:
        """Get class name from ClassId."""
        if isinstance(cls_id, str):
            return cls_id
        return str(cls_id)
    
    def _get_assoc_name(self, assoc_id) -> str:
        """Get association name from AssocId."""
        if isinstance(assoc_id, str):
            return assoc_id
        return str(assoc_id)


# -----------------------------------------------------------------------------
# cvc5 backend (export SMT-LIB2, run cvc5 binary)
# -----------------------------------------------------------------------------

def _check_with_cvc5(
    solver: z3.Solver,
    timeout_ms: Optional[int],
    start_time: float,
) -> tuple[object, float]:
    """
    Export solver to SMT-LIB2, run cvc5 binary, return (z3.sat | z3.unsat | None, elapsed_ms).
    Returns None for unknown or on error. timeout_ms None or 0 = no time limit.
    """
    elapsed = (time.time() - start_time) * 1000
    try:
        smt2 = solver.to_smt2()
    except Exception:
        return (None, elapsed)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".smt2",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(smt2)
        path = f.name
    t0 = time.perf_counter()
    cvc5_args = ["cvc5", path]
    if timeout_ms is not None and timeout_ms > 0:
        cvc5_args = ["cvc5", f"--tlimit={timeout_ms}", path]
    subprocess_timeout = (timeout_ms / 1000) + 60 if (timeout_ms and timeout_ms > 0) else None
    try:
        proc = subprocess.run(
            cvc5_args,
            capture_output=True,
            text=True,
            timeout=subprocess_timeout,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for line in out.splitlines():
            line = line.strip().lower()
            if line == "sat":
                return (z3.sat, elapsed)
            if line == "unsat":
                return (z3.unsat, elapsed)
            if line == "unknown":
                return (None, elapsed)
        return (None, elapsed)
    except FileNotFoundError:
        return (None, (time.perf_counter() - t0) * 1000)
    except subprocess.TimeoutExpired:
        return (None, timeout_ms)
    except Exception:
        return (None, (time.perf_counter() - t0) * 1000)
    finally:
        try:
            import os
            os.unlink(path)
        except Exception:
            pass


def _extract_counterexample(
    z3_model: z3.ModelRef,
    model_encoder: "SMTModelEncoder",
    rule_encoder: "SMTRuleEncoder",
) -> dict:
    """Extract a human-readable counterexample from a satisfying Z3 model."""
    def eval_bool(b: z3.BoolRef) -> bool:
        try:
            val = z3_model.evaluate(b)
            return z3.is_true(val)
        except Exception:
            return False

    out: dict = {
        "source_elements": {},
        "target_elements": {},
        "source_links": {},
        "target_links": {},
        "rule_firings": [],
    }
    for cls_name, vars_list in model_encoder.source_exists.items():
        out["source_elements"][cls_name] = [i for i, v in enumerate(vars_list) if eval_bool(v)]
    for cls_name, vars_list in model_encoder.target_exists.items():
        out["target_elements"][cls_name] = [i for i, v in enumerate(vars_list) if eval_bool(v)]
    for assoc_name, matrix in model_encoder.source_relations.items():
        pairs = []
        for s, row in enumerate(matrix):
            for t, v in enumerate(row):
                if eval_bool(v):
                    pairs.append((s, t))
        out["source_links"][assoc_name] = pairs
    for assoc_name, matrix in model_encoder.target_relations.items():
        pairs = []
        for s, row in enumerate(matrix):
            for t, v in enumerate(row):
                if eval_bool(v):
                    pairs.append((s, t))
        out["target_links"][assoc_name] = pairs
    for rule_id, binding_to_var in rule_encoder.fires.items():
        rule_name = str(rule_id)
        for binding, fires_var in binding_to_var.items():
            if eval_bool(fires_var):
                out["rule_firings"].append({"rule": rule_name, "binding": binding})
    return out


# -----------------------------------------------------------------------------
# SMT Direct Verifier
# -----------------------------------------------------------------------------

class SMTDirectVerifier:
    """
    Main orchestration class for direct SMT-based verification.
    
    Takes a ParsedSpec and verifies all properties using direct SMT encoding.
    """
    
    def __init__(self, spec: ParsedSpec, config: Optional[SMTDirectConfig] = None):
        self.spec = spec
        self.config = config or SMTDirectConfig()
        if not spec.transformations:
            raise ValueError("No transformation found in specification")
        self.transformation = spec.transformations[0]

    def _unsupported_feature_reason(
        self,
        prop: Property,
        relevant_rules: Optional[Set[RuleId]],
    ) -> Optional[str]:
        """Return a reason string when the current SMT encoding cannot support a feature."""
        if prop.precondition is not None:
            for elem in prop.precondition.elements:
                if elem.match_type == MatchType.EXISTS:
                    return f"property precondition uses unsupported EXISTS match element '{elem.name}'"
            for link in prop.precondition.links:
                if link.kind == LinkKind.INDIRECT:
                    return f"property precondition uses unsupported indirect link '{link.name}'"

        rules_to_check = (
            [r for r in self.transformation.all_rules if r.id in relevant_rules]
            if relevant_rules is not None
            else list(self.transformation.all_rules)
        )
        for rule in rules_to_check:
            for elem in rule.match_elements:
                if elem.match_type == MatchType.EXISTS:
                    return f"rule '{rule.name}' uses unsupported EXISTS match element '{elem.name}'"
            for link in rule.match_links:
                if link.kind == LinkKind.INDIRECT:
                    return f"rule '{rule.name}' uses unsupported indirect link '{link.name}'"
        return None

    def _auto_incremental_fallback_reason(
        self,
        stats: PropertySolverStats,
        *,
        use_incremental: bool,
    ) -> Optional[str]:
        """Return a conservative reason to retry with exact incremental checks."""
        if use_incremental:
            return None
        if self.config.solver_backend != "z3":
            return None
        if not self.config.auto_incremental_fallback:
            return None
        if stats.used_factored_post:
            return None
        if stats.post_full_bindings < self.config.auto_incremental_min_post_full_bindings:
            return None
        if stats.pre_bindings > self.config.auto_incremental_max_pre_bindings:
            return None
        if stats.violation_count > self.config.auto_incremental_max_violation_count:
            return None
        return (
            "dangerous monolithic encoding shape "
            f"(pre_bindings={stats.pre_bindings}, "
            f"violations={stats.violation_count}, "
            f"post_full_bindings={stats.post_full_bindings})"
        )

    @staticmethod
    def _merge_solver_stats(
        first: PropertySolverStats,
        second: PropertySolverStats,
    ) -> PropertySolverStats:
        """Combine the pre-fallback and fallback pass stats for reporting."""
        merged = replace(second)
        for field_name in (
            "encoding_ms",
            "relevance_ms",
            "string_reduction_ms",
            "metamodel_slice_ms",
            "per_class_bounds_ms",
            "model_encoder_ms",
            "rule_encoder_ms",
            "property_encoder_ms",
            "check_ms",
            "refinement_ms",
            "counterexample_ms",
            "solver_calls",
            "refinement_model_inspections",
            "refinement_rounds",
            "refinement_clauses",
            "refined_target_nodes",
            "refined_target_links",
            "incremental_candidates_total",
            "incremental_candidates_checked",
            "incremental_candidates_unsat",
            "incremental_candidates_sat",
            "incremental_candidates_unknown",
        ):
            setattr(merged, field_name, getattr(first, field_name) + getattr(second, field_name))

        for field_name in (
            "pre_bindings",
            "violation_count",
            "post_components",
            "post_component_bindings",
            "post_full_bindings",
        ):
            setattr(merged, field_name, max(getattr(first, field_name), getattr(second, field_name)))

        merged.used_factored_post = first.used_factored_post or second.used_factored_post
        merged.phase = second.phase or first.phase
        merged.exception_phase = second.exception_phase or first.exception_phase
        merged.auto_incremental_fallback_suggested = (
            first.auto_incremental_fallback_suggested
            or second.auto_incremental_fallback_suggested
        )
        merged.auto_incremental_fallback_used = (
            first.auto_incremental_fallback_used
            or second.auto_incremental_fallback_used
        )
        merged.auto_incremental_fallback_reason = (
            second.auto_incremental_fallback_reason
            or first.auto_incremental_fallback_reason
        )
        return merged
    
    def verify_all(self) -> DirectVerificationResult:
        """Verify all properties in the specification."""
        start_time = time.time()
        
        results = []
        for prop in self.spec.properties:
            result = self.verify_property(prop)
            results.append(result)
        
        total_time = (time.time() - start_time) * 1000
        
        holds = sum(1 for r in results if r.result == CheckResult.HOLDS)
        violated = sum(1 for r in results if r.result == CheckResult.VIOLATED)
        unknown = sum(1 for r in results if r.result == CheckResult.UNKNOWN)
        complete = sum(1 for r in results if r.is_complete)
        
        return DirectVerificationResult(
            transformation_name=self.transformation.name,
            bound=self.config.bound,
            property_results=tuple(results),
            total_time_ms=total_time,
            holds_count=holds,
            violated_count=violated,
            unknown_count=unknown,
            complete_count=complete,
        )

    def _property_bound(
        self,
        prop: Property,
        *,
        ignore_containment_for_arity: bool,
    ) -> tuple[int, bool, Optional[int]]:
        """Return (bound, is_complete, cutoff_K) for a verification pass."""
        bound = self.config.bound
        is_complete = False
        cutoff_K: Optional[int] = None
        if not self.config.use_cutoff:
            return bound, is_complete, cutoff_K

        in_fragment, _violations = check_fragment(self.transformation, prop)
        if not in_fragment:
            return bound, is_complete, cutoff_K

        K = compute_cutoff_bound(
            self.transformation,
            prop,
            dependency_mode=self.config.dependency_mode,
            ignore_containment_for_arity=ignore_containment_for_arity,
        )
        cutoff_K = K
        is_complete = True
        if self.config.max_cutoff_bound is not None:
            if K > self.config.max_cutoff_bound:
                K = self.config.max_cutoff_bound
                is_complete = False
        if self.config.use_per_class_type_bounds:
            if self.config.per_class_bound_mode not in {
                "strict_theorem",
                "aggressive_optimized",
            }:
                raise ValueError(
                    f"Unknown per_class_bound_mode: {self.config.per_class_bound_mode}"
                )
            if self.config.per_class_bound_mode != "strict_theorem":
                is_complete = False
        return K, is_complete, cutoff_K

    def _check_property_once(
        self,
        prop: Property,
        *,
        start_time: float,
        bound: int,
        is_complete: bool,
        cutoff_K: Optional[int],
        relax_source_containment: bool,
    ) -> PropertyVerificationResult:
        """Run one solver pass and return raw result."""
        try:
            stats = PropertySolverStats()

            def copy_property_encoding_stats(prop_stats: PropertyEncodingStats) -> None:
                stats.pre_bindings = prop_stats.pre_bindings
                stats.violation_count = prop_stats.violation_count
                stats.post_components = prop_stats.post_components
                stats.post_component_bindings = prop_stats.post_component_bindings
                stats.post_full_bindings = prop_stats.post_full_bindings
                stats.used_factored_post = prop_stats.used_factored_post

            effective_bound = bound

            def build_result(
                result: CheckResult,
                elapsed: float,
                *,
                message: str,
                counterexample: Optional[dict] = None,
                is_complete_override: Optional[bool] = None,
            ) -> PropertyVerificationResult:
                return PropertyVerificationResult(
                    property_id=prop.id,
                    property_name=prop.name,
                    result=result,
                    time_ms=elapsed,
                    counterexample=counterexample,
                    message=message,
                    is_complete=is_complete if is_complete_override is None else is_complete_override,
                    bound_used=effective_bound,
                    cutoff_K=cutoff_K,
                    stats=stats,
                )

            encode_start = time.perf_counter()
            stats.phase = "solver_setup"

            # Create fresh solver for each property/pass
            if self.config.solver_tactic and self.config.solver_backend == "z3":
                parts = [p.strip() for p in self.config.solver_tactic.split("+") if p.strip()]
                if parts:
                    t = z3.Tactic(parts[0])
                    for p in parts[1:]:
                        t = z3.Then(t, z3.Tactic(p))
                    solver = t.solver()
                else:
                    solver = z3.Solver()
            elif self.config.solver_logic:
                solver = z3.SolverFor(self.config.solver_logic)
            else:
                solver = z3.Solver()
            if self.config.timeout_ms is not None and self.config.timeout_ms > 0:
                solver.set("timeout", self.config.timeout_ms)
            if self.config.random_seed is not None:
                # Z3 accepts "random_seed" and "sat.random_seed" (not "smt.random_seed")
                solver.set("random_seed", self.config.random_seed)
                solver.set("sat.random_seed", self.config.random_seed)

            def timed_check() -> z3.CheckSatResult:
                check_start = time.perf_counter()
                res = solver.check()
                stats.check_ms += (time.perf_counter() - check_start) * 1000
                stats.solver_calls += 1
                return res

            use_lazy_target_world = (
                self.config.lazy_target_world_refinement
                and self.config.solver_backend == "z3"
            )

            # Encode rules (optionally only those relevant to the property)
            relevant_rules = None
            if self.config.use_property_slicing:
                relevant_start = time.perf_counter()
                if self.config.dependency_mode == "trace_aware":
                    relevant_rules = _relevant_rules_trace_aware(self.transformation, prop)
                elif self.config.dependency_mode == "trace_attr_aware":
                    relevant_rules = _relevant_rules_trace_attr_aware(self.transformation, prop)
                else:
                    relevant_rules = get_relevant_rules(self.transformation, prop)
                stats.relevance_ms = (time.perf_counter() - relevant_start) * 1000

            unsupported_reason = self._unsupported_feature_reason(prop, relevant_rules)
            if unsupported_reason is not None:
                stats.encoding_ms = (time.perf_counter() - encode_start) * 1000
                elapsed = (time.time() - start_time) * 1000
                return build_result(
                    CheckResult.UNKNOWN,
                    elapsed,
                    message=f"SMT encoding incomplete for this property: {unsupported_reason}",
                    is_complete_override=False,
                )

            transformation_for_encoding = self.transformation
            if self.config.reduce_unused_string_domains:
                stats.phase = "string_domain_reduction"
                reduction_start = time.perf_counter()
                transformation_for_encoding = _reduce_unused_string_vocabs_for_property(
                    self.transformation,
                    prop,
                    relevant_rules,
                )
                stats.string_reduction_ms = (time.perf_counter() - reduction_start) * 1000

            # Metamodel slicing: compute minimal class/assoc sets
            mm_kwargs: dict = {}
            src_cls_slice: Optional[Set[str]] = None
            tgt_cls_slice: Optional[Set[str]] = None
            if self.config.use_metamodel_slicing and relevant_rules is not None:
                stats.phase = "metamodel_slice"
                mm_start = time.perf_counter()
                s_cls, t_cls, s_assoc, t_assoc = compute_metamodel_slice(
                    transformation_for_encoding, prop, relevant_rules,
                )
                stats.metamodel_slice_ms = (time.perf_counter() - mm_start) * 1000
                src_cls_slice = s_cls
                tgt_cls_slice = t_cls
                mm_kwargs = dict(
                    relevant_src_classes=s_cls,
                    relevant_tgt_classes=t_cls,
                    relevant_src_assocs=s_assoc,
                    relevant_tgt_assocs=t_assoc,
                )

            source_class_bounds: Optional[Dict[str, int]] = None
            target_class_bounds: Optional[Dict[str, int]] = None
            if self.config.use_per_class_type_bounds:
                stats.phase = "per_class_bounds"
                bounds_start = time.perf_counter()
                source_class_bounds, target_class_bounds = _compute_per_class_type_bounds(
                    transformation_for_encoding,
                    prop,
                    relevant_rules,
                    bound,
                    analysis_mode=self.config.per_class_bounds_analysis,
                    relevant_src_classes=src_cls_slice,
                    relevant_tgt_classes=tgt_cls_slice,
                )
                stats.per_class_bounds_ms = (time.perf_counter() - bounds_start) * 1000
                all_bounds = list(source_class_bounds.values()) + list(target_class_bounds.values())
                if all_bounds:
                    effective_bound = max(1, max(all_bounds))

            # Encode models/rules/property
            stats.phase = "model_encoding"
            model_start = time.perf_counter()
            model_encoder = SMTModelEncoder(
                source_mm=transformation_for_encoding.source_metamodel,
                target_mm=transformation_for_encoding.target_metamodel,
                bound=effective_bound,
                solver=solver,
                source_class_bounds=source_class_bounds,
                target_class_bounds=target_class_bounds,
                relax_source_containment_participation=relax_source_containment,
                **mm_kwargs,
            )
            stats.model_encoder_ms = (time.perf_counter() - model_start) * 1000
            stats.phase = "rule_encoding"
            rule_start = time.perf_counter()
            rule_encoder = SMTRuleEncoder(
                transformation=transformation_for_encoding,
                model_encoder=model_encoder,
                solver=solver,
                relevant_rules=relevant_rules,
                trace_consumer_pairs=_compute_trace_consumer_type_pairs(
                    transformation_for_encoding,
                    prop,
                    relevant_rules,
                ),
                prune_unconsumed_trace_producers=self.config.prune_unconsumed_trace_producers,
                eager_target_world_closure=not use_lazy_target_world,
            )
            stats.rule_encoder_ms = (time.perf_counter() - rule_start) * 1000
            prop_encoder = SMTPropertyEncoder(
                model_encoder=model_encoder,
                rule_encoder=rule_encoder,
                use_symmetry_breaking=self.config.enable_property_symmetry_breaking,
            )

            use_incremental = (
                self.config.use_incremental_property_check
                and self.config.solver_backend == "z3"
            )
            sat_model: Optional[z3.ModelRef] = None
            if use_incremental:
                stats.phase = "property_encoding"
                prop_start = time.perf_counter()
                theta, violation_list = prop_encoder.encode_property_violation_list(prop)
                stats.property_encoder_ms = (time.perf_counter() - prop_start) * 1000
                copy_property_encoding_stats(prop_encoder.last_encoding_stats)
                
                if model_encoder.encoding_issues:
                    stats.encoding_ms = (time.perf_counter() - encode_start) * 1000
                    elapsed = (time.time() - start_time) * 1000
                    return build_result(
                        CheckResult.UNKNOWN,
                        elapsed,
                        message="SMT encoding incomplete for this property: " + "; ".join(model_encoder.encoding_issues),
                        is_complete_override=False,
                    )

                if theta is not None:
                    solver.add(theta)
                stats.encoding_ms = (time.perf_counter() - encode_start) * 1000
                check_result = z3.unknown
                n_total = len(violation_list)
                stats.incremental_candidates_total = n_total
                for idx, v in enumerate(violation_list):
                    while True:
                        stats.phase = "solver_check"
                        solver.push()
                        solver.add(v)
                        stats.incremental_candidates_checked += 1
                        res = timed_check()
                        if res == z3.sat:
                            stats.incremental_candidates_sat += 1
                            candidate_model = solver.model()
                            if use_lazy_target_world:
                                stats.phase = "lazy_refinement"
                                refine_start = time.perf_counter()
                                refinement_batch = rule_encoder.target_world_refinements_for_model(
                                    candidate_model
                                )
                                stats.refinement_ms += (time.perf_counter() - refine_start) * 1000
                                stats.refinement_model_inspections += 1
                                if refinement_batch.constraints:
                                    stats.refinement_rounds += 1
                                    stats.refinement_clauses += len(refinement_batch.constraints)
                                    stats.refined_target_nodes += refinement_batch.refined_target_nodes
                                    stats.refined_target_links += refinement_batch.refined_target_links
                                    solver.pop()
                                    solver.add(*refinement_batch.constraints)
                                    continue
                            sat_model = candidate_model
                            check_result = z3.sat
                            solver.pop()
                            break
                        solver.pop()
                        check_result = res
                        if res == z3.unknown:
                            stats.incremental_candidates_unknown += 1
                            reason = ""
                            try:
                                reason = solver.reason_unknown()
                            except Exception:
                                pass
                            if self.config.verbose:
                                print(f"      candidate {idx}/{n_total}: UNKNOWN ({reason})", flush=True)
                            check_result = z3.unknown
                            break
                        stats.incremental_candidates_unsat += 1
                        if self.config.verbose and idx % max(1, n_total // 10) == 0:
                            print(f"      candidate {idx}/{n_total}: unsat", flush=True)
                        break
                    if check_result != z3.unsat:
                        break
                else:
                    check_result = z3.unsat
                elapsed = (time.time() - start_time) * 1000
            else:
                stats.phase = "property_encoding"
                prop_start = time.perf_counter()
                violation_constraint = prop_encoder.encode_property(prop, solver)
                stats.property_encoder_ms = (time.perf_counter() - prop_start) * 1000
                copy_property_encoding_stats(prop_encoder.last_encoding_stats)
                
                if model_encoder.encoding_issues:
                    stats.encoding_ms = (time.perf_counter() - encode_start) * 1000
                    elapsed = (time.time() - start_time) * 1000
                    return build_result(
                        CheckResult.UNKNOWN,
                        elapsed,
                        message="SMT encoding incomplete for this property: " + "; ".join(model_encoder.encoding_issues),
                        is_complete_override=False,
                    )

                fallback_reason = self._auto_incremental_fallback_reason(
                    stats,
                    use_incremental=use_incremental,
                )
                if fallback_reason is not None:
                    stats.encoding_ms = (time.perf_counter() - encode_start) * 1000
                    stats.phase = "auto_incremental_fallback"
                    stats.auto_incremental_fallback_suggested = True
                    stats.auto_incremental_fallback_reason = fallback_reason
                    elapsed = (time.time() - start_time) * 1000
                    return build_result(
                        CheckResult.UNKNOWN,
                        elapsed,
                        message=_AUTO_INCREMENTAL_FALLBACK_SENTINEL,
                    )

                solver.add(violation_constraint)
                stats.encoding_ms = (time.perf_counter() - encode_start) * 1000
                if self.config.solver_backend == "cvc5":
                    check_result, elapsed = _check_with_cvc5(
                        solver,
                        self.config.timeout_ms if self.config.timeout_ms and self.config.timeout_ms > 0 else None,
                        start_time,
                    )
                else:
                    while True:
                        stats.phase = "solver_check"
                        check_result = timed_check()
                        if check_result != z3.sat or not use_lazy_target_world:
                            break
                        candidate_model = solver.model()
                        stats.phase = "lazy_refinement"
                        refine_start = time.perf_counter()
                        refinement_batch = rule_encoder.target_world_refinements_for_model(
                            candidate_model
                        )
                        stats.refinement_ms += (time.perf_counter() - refine_start) * 1000
                        stats.refinement_model_inspections += 1
                        if not refinement_batch.constraints:
                            sat_model = candidate_model
                            break
                        stats.refinement_rounds += 1
                        stats.refinement_clauses += len(refinement_batch.constraints)
                        stats.refined_target_nodes += refinement_batch.refined_target_nodes
                        stats.refined_target_links += refinement_batch.refined_target_links
                        solver.add(*refinement_batch.constraints)
                    elapsed = (time.time() - start_time) * 1000

            if check_result == z3.sat:
                z3_model = sat_model if use_incremental else solver.model()
                stats.phase = "counterexample_extraction"
                cx_start = time.perf_counter()
                counterexample = _extract_counterexample(z3_model, model_encoder, rule_encoder)
                stats.counterexample_ms += (time.perf_counter() - cx_start) * 1000
                return build_result(
                    CheckResult.VIOLATED,
                    elapsed,
                    message="Counterexample found",
                    counterexample=counterexample,
                )
            if check_result == z3.unsat:
                return build_result(
                    CheckResult.HOLDS,
                    elapsed,
                    message="Verified",
                )

            reason = "Timeout or unknown"
            if self.config.solver_backend != "cvc5":
                try:
                    reason = solver.reason_unknown()
                except Exception:
                    pass
            return build_result(
                CheckResult.UNKNOWN,
                elapsed,
                message=reason,
            )
        except Exception as e:
            stats.exception_phase = stats.phase
            elapsed = (time.time() - start_time) * 1000
            raw_message = str(e)
            normalized_message = raw_message
            lower_message = raw_message.lower()
            if "out of memory" in lower_message:
                normalized_message = "out of memory"
            elif "overflow encountered when expanding vector" in lower_message:
                normalized_message = "Overflow encountered when expanding vector"
            if stats.exception_phase:
                normalized_message = f"{normalized_message} (during {stats.exception_phase})"
            return PropertyVerificationResult(
                property_id=prop.id,
                property_name=prop.name,
                result=CheckResult.UNKNOWN,
                time_ms=elapsed,
                message=normalized_message,
                is_complete=is_complete,
                bound_used=bound,
                cutoff_K=cutoff_K,
                stats=stats,
            )

    def _verify_property_atomic(self, prop: Property) -> PropertyVerificationResult:
        """Verify one already-lowered property against this verifier's spec."""
        start_time = time.time()
        relaxed_mode = self.config.relax_source_containment_for_proving

        bound, is_complete, cutoff_K = self._property_bound(
            prop,
            ignore_containment_for_arity=relaxed_mode,
        )
        if relaxed_mode:
            # Relaxed containment mode is an optimization profile; do not claim
            # theorem completeness from reduced K alone.
            is_complete = False
        primary = self._check_property_once(
            prop,
            start_time=start_time,
            bound=bound,
            is_complete=is_complete,
            cutoff_K=cutoff_K,
            relax_source_containment=relaxed_mode,
        )

        if (
            primary.message == _AUTO_INCREMENTAL_FALLBACK_SENTINEL
            and primary.stats.auto_incremental_fallback_suggested
            and not self.config.use_incremental_property_check
        ):
            fallback_verifier = SMTDirectVerifier(
                self.spec,
                replace(
                    self.config,
                    use_incremental_property_check=True,
                    auto_incremental_fallback=False,
                ),
            )
            fallback_result = fallback_verifier._check_property_once(
                prop,
                start_time=start_time,
                bound=bound,
                is_complete=is_complete,
                cutoff_K=cutoff_K,
                relax_source_containment=relaxed_mode,
            )
            fallback_result.stats = self._merge_solver_stats(primary.stats, fallback_result.stats)
            fallback_result.stats.auto_incremental_fallback_used = True
            if fallback_result.result == CheckResult.HOLDS:
                fallback_result.message = "Verified after automatic incremental fallback"
            elif fallback_result.result == CheckResult.VIOLATED:
                fallback_result.message = "Counterexample found after automatic incremental fallback"
            else:
                fallback_result.message = (
                    f"{fallback_result.message}; after automatic incremental fallback"
                )
            primary = fallback_result

        # Optional strict confirmation for candidate violations from relaxed mode.
        if not (
            relaxed_mode
            and self.config.strict_recheck_on_relaxed_sat
            and primary.result == CheckResult.VIOLATED
        ):
            if relaxed_mode and primary.result == CheckResult.HOLDS:
                primary.message = "Verified under containment-relaxed proving profile"
            return primary

        strict_bound, strict_complete, strict_cutoff = self._property_bound(
            prop,
            ignore_containment_for_arity=False,
        )
        strict_result = self._check_property_once(
            prop,
            start_time=start_time,
            bound=strict_bound,
            is_complete=strict_complete,
            cutoff_K=strict_cutoff,
            relax_source_containment=False,
        )
        if strict_result.result == CheckResult.VIOLATED:
            strict_result.message = (
                "Counterexample found (confirmed by strict containment recheck)"
            )
            return strict_result
        if strict_result.result == CheckResult.HOLDS:
            strict_result.message = (
                "Relaxed SAT was spurious; verified with strict containment recheck"
            )
            return strict_result
        strict_result.message = (
            "Relaxed mode found a candidate counterexample, but strict containment recheck "
            f"returned {strict_result.result.value}: {strict_result.message}"
        )
        return strict_result

    def verify_property(self, prop: Property) -> PropertyVerificationResult:
        """Verify a single property, flattening inheritance internally when needed."""
        flat_bundle = flatten_spec_for_property(self.spec, prop)
        if not flat_bundle.applied:
            return self._verify_property_atomic(prop)

        flat_results = [
            SMTDirectVerifier(variant.spec, self.config)._verify_property_atomic(variant.property)
            for variant in flat_bundle.variants
        ]
        if not flat_results:
            # Defensive fallback: if flattening produces no concrete variants for a property,
            # verify the original property atomically instead of crashing.
            fallback = self._verify_property_atomic(prop)
            if fallback.message:
                fallback.message = (
                    "Flattening produced no variants; used atomic fallback. "
                    + fallback.message
                )
            else:
                fallback.message = "Flattening produced no variants; used atomic fallback."
            return fallback
        total_time = sum(r.time_ms for r in flat_results)
        max_bound = max((r.bound_used for r in flat_results), default=0)
        max_cutoff = max((r.cutoff_K for r in flat_results if r.cutoff_K is not None), default=None)

        violated = next((r for r in flat_results if r.result == CheckResult.VIOLATED), None)
        if violated is not None:
            return PropertyVerificationResult(
                property_id=prop.id,
                property_name=prop.name,
                result=CheckResult.VIOLATED,
                time_ms=total_time,
                counterexample=lift_counterexample(
                    violated.counterexample,
                    original_transformation=flat_bundle.original_transformation,
                    rule_name_map=flat_bundle.rule_name_map,
                    assoc_origin_map=flat_bundle.assoc_origin_map,
                ),
                message=violated.message,
                is_complete=violated.is_complete,
                bound_used=max_bound,
                cutoff_K=max_cutoff,
                stats=violated.stats,
            )

        unknown = next((r for r in flat_results if r.result == CheckResult.UNKNOWN), None)
        if unknown is not None:
            return PropertyVerificationResult(
                property_id=prop.id,
                property_name=prop.name,
                result=CheckResult.UNKNOWN,
                time_ms=total_time,
                counterexample=None,
                message=unknown.message,
                is_complete=False,
                bound_used=max_bound,
                cutoff_K=max_cutoff,
                stats=unknown.stats,
            )

        representative = flat_results[0]
        return PropertyVerificationResult(
            property_id=prop.id,
            property_name=prop.name,
            result=CheckResult.HOLDS,
            time_ms=total_time,
            counterexample=None,
            message=representative.message,
            is_complete=all(r.is_complete for r in flat_results),
            bound_used=max_bound,
            cutoff_K=max_cutoff,
            stats=representative.stats,
        )


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def verify_direct(
    spec: ParsedSpec,
    bound: int = 5,
    timeout_ms: int = 30000,
    verbose: bool = False,
    use_cutoff: bool = True,
    max_cutoff_bound: Optional[int] = None,
    use_property_slicing: bool = False,
    solver_backend: str = "z3",
    relax_source_containment_for_proving: bool = False,
    strict_recheck_on_relaxed_sat: bool = True,
    enable_property_symmetry_breaking: bool = False,
    reduce_unused_string_domains: bool = False,
    prune_unconsumed_trace_producers: bool = False,
    use_per_class_type_bounds: bool = False,
    per_class_bounds_analysis: str = "simple",
    per_class_bound_mode: str = "aggressive_optimized",
) -> DirectVerificationResult:
    """
    Verify all properties in a DSLTrans specification using direct SMT encoding.

    When use_cutoff is True and (transformation, property) is in F-LNR × G-BPP,
    uses property-specific cutoff bound K for complete verification.

    Args:
        spec: Parsed DSLTrans specification
        bound: Fallback max elements per type when cutoff not used
        timeout_ms: Timeout per property in milliseconds
        verbose: Enable verbose output
        use_cutoff: Use cutoff theorem to set bound per property when in fragment
        max_cutoff_bound: Cap on K for tractability (None = no cap)
        use_property_slicing: Encode only rules relevant to each property (smaller formula)
        solver_backend: "z3" (default) or "cvc5" (export SMT-LIB2 and run cvc5 binary)
        relax_source_containment_for_proving: Relax source containment participation
            constraints and ignore containment arity in K as a proving heuristic
        strict_recheck_on_relaxed_sat: Recheck relaxed SAT candidates with strict
            containment semantics before reporting VIOLATED
        enable_property_symmetry_breaking: Enable safe symmetry-breaking constraints
            in postcondition component binding enumeration
        reduce_unused_string_domains: Collapse finite String vocabularies for
            attributes that are unused by the relevant property/rules
        prune_unconsumed_trace_producers: Record only trace producers for
            source/target class pairs consumed by backward links or property
            postcondition trace links
        use_per_class_type_bounds: Use per-class bounds (instead of uniform K
            per class) to shrink formulas
        per_class_bounds_analysis: Per-class bounds profile ("simple" or
            "fixed_point") when use_per_class_type_bounds=True
        per_class_bound_mode: Completeness policy for per-class bounds.
            ``"strict_theorem"`` treats the theorem-aligned fixed-point bounds
            as cutoff-complete; ``"aggressive_optimized"`` keeps the current
            optimization-first behavior and reports incomplete.

    Returns:
        DirectVerificationResult with results for all properties
    """
    config = SMTDirectConfig(
        bound=bound,
        timeout_ms=timeout_ms,
        verbose=verbose,
        use_cutoff=use_cutoff,
        max_cutoff_bound=max_cutoff_bound,
        use_property_slicing=use_property_slicing,
        solver_backend=solver_backend,
        relax_source_containment_for_proving=relax_source_containment_for_proving,
        strict_recheck_on_relaxed_sat=strict_recheck_on_relaxed_sat,
        enable_property_symmetry_breaking=enable_property_symmetry_breaking,
        reduce_unused_string_domains=reduce_unused_string_domains,
        prune_unconsumed_trace_producers=prune_unconsumed_trace_producers,
        use_per_class_type_bounds=use_per_class_type_bounds,
        per_class_bounds_analysis=per_class_bounds_analysis,
        per_class_bound_mode=per_class_bound_mode,
    )

    verifier = SMTDirectVerifier(spec, config)
    return verifier.verify_all()
