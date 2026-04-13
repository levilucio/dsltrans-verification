"""
DSLTrans Property Checking

Implements property verification on path conditions.

Properties are pre-condition/post-condition pairs:
  "If Pre matches in input, then Post matches in output"

Two modes of checking:
  1. Pattern-based (fast, but incomplete): Direct pattern matching on symbolic graph
  2. SMT-based (complete, slower): Z3 constraint solving for full semantic check

See: dsltrans.tex Section E.4.8 (Property Specification and Verification)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import re

from .model import (
    Transformation, Property,
    MatchElement, ApplyElement, MatchLink, ApplyLink,
    ClassId, ElementId,
)
from .path_condition import PathCondition, SymVertex, SymEdge, SymTraceLink


class CheckMode(Enum):
    """Property checking mode."""
    PATTERN = "pattern"  # Fast pattern matching (may have false positives/negatives)
    SMT = "smt"          # Complete SMT-based checking


@dataclass(frozen=True)
class PropertyResult:
    """Result of property verification."""
    property_id: str
    property_name: str
    status: str  # "holds", "violated", "unknown"
    counterexample_pcs: tuple[int, ...] = ()
    counterexample_model: Optional[dict] = None  # SMT counterexample
    witness_trace: Optional[str] = None


def check_property(
    pc: PathCondition,
    prop: Property,
    transformation: Transformation,
    mode: CheckMode = CheckMode.SMT,
) -> bool:
    """
    Check if a property holds on a path condition.
    
    Args:
        pc: Path condition to check
        prop: Property to verify
        transformation: The transformation being verified
        mode: Checking mode (SMT for complete, PATTERN for fast)
    
    Returns:
        True if property holds, False otherwise
    
    See: dsltrans.tex Definition 24 (Property Satisfaction by Path Condition)
    """
    if mode == CheckMode.SMT:
        return _check_property_smt(pc, prop, transformation)
    else:
        return _check_property_pattern(pc, prop, transformation)


def _check_property_smt(
    pc: PathCondition,
    prop: Property,
    transformation: Transformation,
) -> bool:
    """
    Check property using SMT solving (complete but slower).
    
    Uses Z3 to verify that no concrete model exists where:
      - The model is abstractable to the path condition
      - The precondition pattern matches
      - The postcondition pattern does NOT match
    """
    raise NotImplementedError("Deprecated SMT checker removed. Use smt_direct.py instead.")
    return result.holds


def _check_property_pattern(
    pc: PathCondition,
    prop: Property,
    transformation: Transformation,
) -> bool:
    """
    Check property using pattern matching (fast but incomplete).
    
    NOTE: This is a simplified check that may produce false results
    because it treats symbolic elements from different rules as distinct
    when they might represent the same concrete element.
    
    Algorithm:
      1. If no precondition, check postcondition unconditionally
      2. Search for precondition in match graph
      3. If found, search for postcondition (with traceability) in full PC
      4. Property holds iff: whenever pre is found, post is also found
    """
    # Empty precondition means postcondition must hold unconditionally
    if prop.precondition is None or len(prop.precondition.elements) == 0:
        return _check_postcondition_unconditional(pc, prop, transformation)
    
    # Find all matches of precondition in the match graph
    pre_matches = _find_pattern_matches(
        pc,
        prop.precondition.elements,
        prop.precondition.links,
        match_only=True,
    )
    
    if not pre_matches:
        # Precondition never satisfied -> property vacuously holds
        return True
    
    # For each precondition match, check if postcondition is satisfied
    for pre_binding in pre_matches:
        if not _check_postcondition_with_trace(pc, prop, pre_binding, transformation):
            return False
    
    return True


def _check_postcondition_unconditional(
    pc: PathCondition,
    prop: Property,
    transformation: Transformation,
) -> bool:
    """Check postcondition without precondition constraint."""
    # Postcondition elements must exist in apply graph
    post_matches = _find_pattern_matches(
        pc,
        prop.postcondition.elements,
        prop.postcondition.links,
        match_only=False,
    )
    return len(post_matches) > 0


def _check_postcondition_with_trace(
    pc: PathCondition,
    prop: Property,
    pre_binding: dict[ElementId, str],
    transformation: Transformation,
) -> bool:
    """
    Check postcondition with traceability constraint.
    
    The postcondition elements must:
      1. Exist in the apply graph
      2. Have trace links connecting them to the precondition elements
    """
    # Find postcondition matches
    post_matches = _find_pattern_matches(
        pc,
        prop.postcondition.elements,
        prop.postcondition.links,
        match_only=False,
    )
    
    if not post_matches:
        return False
    
    # Check traceability constraints
    for post_binding in post_matches:
        if _check_trace_constraints(pc, prop, pre_binding, post_binding):
            return True
    
    return False


def _check_trace_constraints(
    pc: PathCondition,
    prop: Property,
    pre_binding: dict[ElementId, str],
    post_binding: dict[ElementId, str],
) -> bool:
    """Check if trace links connect post elements to pre elements."""
    for post_elem_id, pre_elem_id in prop.postcondition.trace_links:
        if post_elem_id not in post_binding or pre_elem_id not in pre_binding:
            continue
        
        post_vertex_id = post_binding[post_elem_id]
        pre_vertex_id = pre_binding[pre_elem_id]
        
        # Check if there's a trace link from post to pre
        found_trace = False
        for trace in pc.trace_links:
            if trace.apply_vertex == post_vertex_id and trace.match_vertex == pre_vertex_id:
                found_trace = True
                break
        
        if not found_trace:
            return False
    
    return True


def _find_pattern_matches(
    pc: PathCondition,
    elements: tuple[MatchElement | ApplyElement, ...],
    links: tuple[MatchLink | ApplyLink, ...],
    match_only: bool,
) -> list[dict[ElementId, str]]:
    """
    Find all matches of a pattern in the path condition.
    
    Returns list of bindings: element_id -> vertex_id
    """
    if not elements:
        return [{}]
    
    # Get relevant vertices
    if match_only:
        vertices = list(pc.match_vertices)
    else:
        vertices = list(pc.apply_vertices)
    
    # Simple backtracking search for pattern match
    bindings: list[dict[ElementId, str]] = []
    
    def search(elem_idx: int, current_binding: dict[ElementId, str]) -> None:
        if elem_idx >= len(elements):
            # Check links
            if _check_links(pc, links, current_binding, match_only):
                bindings.append(dict(current_binding))
            return
        
        elem = elements[elem_idx]
        for v in vertices:
            # Type check
            if v.class_type != elem.class_type:
                continue
            
            # Not already bound
            if v.id in current_binding.values():
                continue
            
            current_binding[elem.id] = v.id
            search(elem_idx + 1, current_binding)
            del current_binding[elem.id]
    
    search(0, {})
    return bindings


def _check_links(
    pc: PathCondition,
    links: tuple[MatchLink | ApplyLink, ...],
    binding: dict[ElementId, str],
    match_only: bool,
) -> bool:
    """Check if all links in pattern are satisfied by binding."""
    edges = pc.match_edges if match_only else pc.apply_edges
    
    for link in links:
        if link.source not in binding or link.target not in binding:
            continue
        
        src_v = binding[link.source]
        tgt_v = binding[link.target]
        
        # Find matching edge
        found = False
        for e in edges:
            if e.source == src_v and e.target == tgt_v and e.assoc_type == link.assoc_type:
                found = True
                break
        
        if not found:
            return False
    
    return True


# -----------------------------------------------------------------------------
# Composite Property Evaluation
# -----------------------------------------------------------------------------

def evaluate_composite_formula(
    formula: str,
    atomic_results: dict[str, bool],
) -> bool:
    """
    Evaluate a propositional formula over atomic contract results.
    
    Operators: and, or, not, implies
    Operands: atomic contract IDs
    """
    # Simple expression evaluator
    # Replace atomic IDs with their boolean values
    expr = formula
    
    for atomic_id, result in atomic_results.items():
        expr = re.sub(rf'\b{re.escape(atomic_id)}\b', str(result), expr)
    
    # Replace operators
    expr = expr.replace(" implies ", " <= ")  # P implies Q = not P or Q
    expr = expr.replace(" and ", " and ")
    expr = expr.replace(" or ", " or ")
    expr = expr.replace("not ", "not ")
    
    try:
        return eval(expr, {"__builtins__": {}}, {"True": True, "False": False})
    except Exception:
        # If evaluation fails, conservatively return False
        return False
