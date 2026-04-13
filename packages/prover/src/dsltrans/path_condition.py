"""
DSLTrans Path Condition - Kernel State Representation

Implements the symbolic state (U, S, Θ) for DSLTrans:
  - U = V_sym ∪ E_sym ∪ A_sym (symbolic entities)
  - S = ⟨Match, Apply, Adj, Trace, RuleCopies, ℓ⟩ (structure)
  - Θ = Θ_typing ∪ Θ_structural ∪ Θ_attr (constraints)

Key abstraction: Rule execution count → presence/absence (0 vs ≥1)
Each path condition represents all executions using the same set of rules.

See: dsltrans.tex Definition 18 (Symbolic State for DSLTrans)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Iterator
from functools import cached_property
import hashlib

from .model import (
    Rule, RuleId, ElementId, ClassId, AssocId,
    MatchElement, ApplyElement, MatchLink, ApplyLink, BackwardLink,
    AttributeConstraint, Expr,
)


# -----------------------------------------------------------------------------
# Symbolic Entities (Universe U)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class SymVertex:
    """Symbolic vertex in path condition."""
    id: str
    class_type: ClassId
    from_rule: RuleId
    is_match: bool  # True = match element, False = apply element


@dataclass(frozen=True)
class SymEdge:
    """Symbolic edge in path condition."""
    id: str
    assoc_type: AssocId
    source: str  # SymVertex id
    target: str  # SymVertex id
    from_rule: RuleId
    is_match: bool


@dataclass(frozen=True)
class SymTraceLink:
    """Symbolic traceability link from apply to match element."""
    id: str
    apply_vertex: str  # SymVertex id (apply element)
    match_vertex: str  # SymVertex id (match element)
    from_rule: RuleId


# -----------------------------------------------------------------------------
# Multi-Location Matching (Lucio2014 Section 4.4)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class BackwardBinding:
    """
    A binding for a single backward link to an existing trace link.
    
    Maps a rule's backward link to a specific traceability link in the PC.
    """
    backward_link_match_elem: ElementId  # Rule's match element id
    backward_link_apply_elem: ElementId  # Rule's apply element id
    pc_trace_link_id: str  # ID of matching trace link in PC
    pc_apply_vertex_id: str  # Apply vertex in PC
    pc_match_vertex_id: str  # Match vertex in PC


@dataclass(frozen=True)
class MatchLocation:
    """
    A complete matching location for a rule in a path condition.
    
    Represents one specific way a rule's backward links can bind to
    existing traceability links in the PC.
    
    For a rule with N backward links, a MatchLocation contains N bindings,
    one for each backward link.
    """
    bindings: tuple[BackwardBinding, ...]
    is_total: bool  # True if all match elements are constrained (no free elements)
    
    @cached_property
    def binding_key(self) -> tuple:
        """Unique key for this location based on bound PC elements."""
        return tuple(sorted(
            (b.pc_apply_vertex_id, b.pc_match_vertex_id)
            for b in self.bindings
        ))
    
    def __hash__(self) -> int:
        return hash(self.bindings)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MatchLocation):
            return NotImplemented
        return self.bindings == other.bindings


@dataclass
class MatchResult:
    """
    Result of checking backward dependencies with multi-location support.
    
    Contains all possible matching locations for a rule in a PC.
    """
    can_execute: bool  # True if at least one valid matching exists
    locations: tuple[MatchLocation, ...]  # All valid matching locations
    has_free_elements: bool  # True if some match elements have no backward link
    has_attribute_constraints: bool  # True if guard or where clauses exist
    
    @property
    def must_execute_at_all(self) -> bool:
        """
        True if rule must execute at ALL locations (totally satisfied case).
        
        This happens when:
          - All match elements are constrained by backward links
          - No attribute constraints that could block execution
        """
        if not self.locations:
            return False
        return all(loc.is_total for loc in self.locations) and not self.has_attribute_constraints
    
    @property
    def is_partial(self) -> bool:
        """
        True if this is a partial matching case (may or may not fire at each location).
        """
        if not self.can_execute:
            return False
        return self.has_free_elements or self.has_attribute_constraints


# -----------------------------------------------------------------------------
# Path Condition (Symbolic State)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class PathCondition:
    """
    Symbolic path condition representing a set of transformation executions.
    
    Kernel mapping:
      - U: vertices ∪ edges ∪ trace_links (symbolic entities)
      - S: Structure encoded by vertices, edges, trace_links, rule_copies, layer_index
      - Θ: Θ_typing ∪ Θ_structural ∪ Θ_attr (constraints)
    
    Key invariant: Each rule appears at most once (multiplicity abstracted).
    """
    # Symbolic entities (U)
    vertices: FrozenSet[SymVertex]
    edges: FrozenSet[SymEdge]
    trace_links: FrozenSet[SymTraceLink]
    
    # Structure (S)
    rule_copies: FrozenSet[RuleId]  # Set of rules combined into this PC
    layer_index: int  # Current layer (1-indexed)
    
    # Constraints (Θ_attr) - attribute constraints accumulated during exploration
    # Typing (Θ_typing) and structural (Θ_structural) constraints are implicit in vertices/edges
    theta_attr: tuple[AttributeConstraint, ...] = ()
    
    @staticmethod
    def empty() -> PathCondition:
        """Create empty path condition (ε_pc)."""
        return PathCondition(
            vertices=frozenset(),
            edges=frozenset(),
            trace_links=frozenset(),
            rule_copies=frozenset(),
            layer_index=1,
            theta_attr=(),
        )
    
    @cached_property
    def is_empty(self) -> bool:
        return len(self.rule_copies) == 0
    
    @cached_property
    def match_vertices(self) -> FrozenSet[SymVertex]:
        """Get all match vertices."""
        return frozenset(v for v in self.vertices if v.is_match)
    
    @cached_property
    def apply_vertices(self) -> FrozenSet[SymVertex]:
        """Get all apply vertices."""
        return frozenset(v for v in self.vertices if not v.is_match)
    
    @cached_property
    def match_edges(self) -> FrozenSet[SymEdge]:
        """Get all match edges."""
        return frozenset(e for e in self.edges if e.is_match)
    
    @cached_property
    def apply_edges(self) -> FrozenSet[SymEdge]:
        """Get all apply edges."""
        return frozenset(e for e in self.edges if not e.is_match)
    
    def vertices_by_type(self, class_type: ClassId) -> FrozenSet[SymVertex]:
        """Get vertices of a specific type."""
        return frozenset(v for v in self.vertices if v.class_type == class_type)
    
    def get_vertex(self, vertex_id: str) -> Optional[SymVertex]:
        """Get vertex by ID."""
        for v in self.vertices:
            if v.id == vertex_id:
                return v
        return None
    
    @cached_property
    def canonical_hash(self) -> str:
        """
        Compute canonical hash for isomorphism-based deduplication.
        
        Two path conditions with the same rule sets and isomorphic
        structures should have the same hash.
        """
        # Sort rule copies for determinism
        rules = tuple(sorted(str(r) for r in self.rule_copies))
        
        # Sort vertices by type and rule
        vertices = tuple(sorted(
            (str(v.class_type), str(v.from_rule), v.is_match)
            for v in self.vertices
        ))
        
        # Sort edges by type and endpoints
        edges = tuple(sorted(
            (str(e.assoc_type), str(e.from_rule), e.is_match)
            for e in self.edges
        ))
        
        # Sort trace links
        traces = tuple(sorted(
            str(t.from_rule) for t in self.trace_links
        ))
        
        # Include constraint fingerprint
        constraints = tuple(sorted(
            (str(c.expr), c.source, str(c.rule_id) if c.rule_id else "")
            for c in self.theta_attr
        ))
        
        content = (rules, vertices, edges, traces, constraints, self.layer_index)
        return hashlib.sha256(str(content).encode()).hexdigest()[:16]
    
    def __hash__(self) -> int:
        return hash((self.vertices, self.edges, self.trace_links, 
                     self.rule_copies, self.layer_index, self.theta_attr))
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PathCondition):
            return NotImplemented
        return (
            self.vertices == other.vertices and
            self.edges == other.edges and
            self.trace_links == other.trace_links and
            self.rule_copies == other.rule_copies and
            self.layer_index == other.layer_index and
            self.theta_attr == other.theta_attr
        )


# -----------------------------------------------------------------------------
# Path Condition Construction Operations
# -----------------------------------------------------------------------------

def combine_rule(
    pc: PathCondition,
    rule: Rule,
    *,
    rule_instance_id: int = 0,
) -> PathCondition:
    """
    Combine a path condition with a rule (trace union operator).
    
    Creates new path condition: pc ∪^trace rl
    
    This adds:
      - All match elements from rule as symbolic vertices
      - All apply elements from rule as symbolic vertices
      - All match links as symbolic edges
      - All apply links as symbolic edges
      - Traceability links from each apply element to all match elements
        (unless connected by backward link)
      - Attribute constraints from where clauses and guards
    
    See: dsltrans.tex Definition 19 (Trace Union Operator)
    """
    prefix = f"{rule.id}_{rule_instance_id}"
    
    # Create symbolic vertices for match elements
    new_match_vertices = frozenset(
        SymVertex(
            id=f"{prefix}_m_{e.id}",
            class_type=e.class_type,
            from_rule=rule.id,
            is_match=True,
        )
        for e in rule.match_elements
    )
    
    # Create symbolic vertices for apply elements
    new_apply_vertices = frozenset(
        SymVertex(
            id=f"{prefix}_a_{e.id}",
            class_type=e.class_type,
            from_rule=rule.id,
            is_match=False,
        )
        for e in rule.apply_elements
    )
    
    # Create symbolic edges for match links
    new_match_edges = frozenset(
        SymEdge(
            id=f"{prefix}_me_{l.id}",
            assoc_type=l.assoc_type,
            source=f"{prefix}_m_{l.source}",
            target=f"{prefix}_m_{l.target}",
            from_rule=rule.id,
            is_match=True,
        )
        for l in rule.match_links
    )
    
    # Create symbolic edges for apply links
    new_apply_edges = frozenset(
        SymEdge(
            id=f"{prefix}_ae_{l.id}",
            assoc_type=l.assoc_type,
            source=f"{prefix}_a_{l.source}",
            target=f"{prefix}_a_{l.target}",
            from_rule=rule.id,
            is_match=False,
        )
        for l in rule.apply_links
    )
    
    # Create traceability links
    # Apply elements NOT connected by backward links get trace links to ALL match elements
    backward_apply_ids = rule.backward_link_apply_elements
    new_trace_links: set[SymTraceLink] = set()
    
    trace_counter = 0
    for apply_elem in rule.apply_elements:
        if apply_elem.id in backward_apply_ids:
            # This apply element is connected via backward link - 
            # its traceability is determined by the backward link
            continue
        
        for match_elem in rule.match_elements:
            new_trace_links.add(SymTraceLink(
                id=f"{prefix}_tr_{trace_counter}",
                apply_vertex=f"{prefix}_a_{apply_elem.id}",
                match_vertex=f"{prefix}_m_{match_elem.id}",
                from_rule=rule.id,
            ))
            trace_counter += 1
    
    # Collect attribute constraints from the rule (lazy accumulation)
    new_constraints: list[AttributeConstraint] = []
    
    # Constraints from match element where clauses
    for match_elem in rule.match_elements:
        if match_elem.where_clause is not None:
            new_constraints.append(AttributeConstraint(
                expr=match_elem.where_clause,
                source="match",
                rule_id=rule.id,
            ))
    
    # Constraints from rule guard
    if rule.guard is not None:
        new_constraints.append(AttributeConstraint(
            expr=rule.guard,
            source="guard",
            rule_id=rule.id,
        ))
    
    return PathCondition(
        vertices=pc.vertices | new_match_vertices | new_apply_vertices,
        edges=pc.edges | new_match_edges | new_apply_edges,
        trace_links=pc.trace_links | frozenset(new_trace_links),
        rule_copies=pc.rule_copies | {rule.id},
        layer_index=pc.layer_index,
        theta_attr=pc.theta_attr + tuple(new_constraints),
    )


def combine_rule_at_location(
    pc: PathCondition,
    rule: Rule,
    location: MatchLocation,
    *,
    rule_instance_id: int = 0,
) -> PathCondition:
    """
    Combine a path condition with a rule at a specific matching location.
    
    This is the "gluing" operation from Lucio2014 Section 4.4:
      - Elements bound via backward links are NOT duplicated
      - Only the "delta" (new elements not in PC) is added
      - Trace links are created only for newly created apply elements
    
    See: dsltrans.tex Definition 22-24 (Partial/Total Combination)
    """
    prefix = f"{rule.id}_{rule_instance_id}"
    
    # Build mapping from rule elements to existing PC vertices via bindings
    match_elem_to_pc_vertex: dict[ElementId, str] = {}
    apply_elem_to_pc_vertex: dict[ElementId, str] = {}
    
    for binding in location.bindings:
        match_elem_to_pc_vertex[binding.backward_link_match_elem] = binding.pc_match_vertex_id
        apply_elem_to_pc_vertex[binding.backward_link_apply_elem] = binding.pc_apply_vertex_id
    
    # Create symbolic vertices for match elements NOT already bound
    new_match_vertices: set[SymVertex] = set()
    match_elem_vertex_map: dict[ElementId, str] = {}  # rule elem id -> vertex id
    
    for e in rule.match_elements:
        if e.id in match_elem_to_pc_vertex:
            # Already bound via backward link - use existing vertex
            match_elem_vertex_map[e.id] = match_elem_to_pc_vertex[e.id]
        else:
            # New match element - create symbolic vertex
            vertex_id = f"{prefix}_m_{e.id}"
            new_match_vertices.add(SymVertex(
                id=vertex_id,
                class_type=e.class_type,
                from_rule=rule.id,
                is_match=True,
            ))
            match_elem_vertex_map[e.id] = vertex_id
    
    # Create symbolic vertices for apply elements NOT already bound
    new_apply_vertices: set[SymVertex] = set()
    apply_elem_vertex_map: dict[ElementId, str] = {}  # rule elem id -> vertex id
    
    for e in rule.apply_elements:
        if e.id in apply_elem_to_pc_vertex:
            # Already bound via backward link - use existing vertex
            apply_elem_vertex_map[e.id] = apply_elem_to_pc_vertex[e.id]
        else:
            # New apply element - create symbolic vertex
            vertex_id = f"{prefix}_a_{e.id}"
            new_apply_vertices.add(SymVertex(
                id=vertex_id,
                class_type=e.class_type,
                from_rule=rule.id,
                is_match=False,
            ))
            apply_elem_vertex_map[e.id] = vertex_id
    
    # Create symbolic edges for match links
    # Only create if both endpoints are new, or if edge doesn't exist
    new_match_edges: set[SymEdge] = set()
    for l in rule.match_links:
        source_id = match_elem_vertex_map.get(l.source)
        target_id = match_elem_vertex_map.get(l.target)
        if source_id and target_id:
            # Check if this edge already exists in PC
            edge_exists = any(
                e.source == source_id and e.target == target_id and e.assoc_type == l.assoc_type
                for e in pc.edges
            )
            if not edge_exists:
                new_match_edges.add(SymEdge(
                    id=f"{prefix}_me_{l.id}",
                    assoc_type=l.assoc_type,
                    source=source_id,
                    target=target_id,
                    from_rule=rule.id,
                    is_match=True,
                ))
    
    # Create symbolic edges for apply links
    new_apply_edges: set[SymEdge] = set()
    for l in rule.apply_links:
        source_id = apply_elem_vertex_map.get(l.source)
        target_id = apply_elem_vertex_map.get(l.target)
        if source_id and target_id:
            # Check if this edge already exists in PC
            edge_exists = any(
                e.source == source_id and e.target == target_id and e.assoc_type == l.assoc_type
                for e in pc.edges
            )
            if not edge_exists:
                new_apply_edges.add(SymEdge(
                    id=f"{prefix}_ae_{l.id}",
                    assoc_type=l.assoc_type,
                    source=source_id,
                    target=target_id,
                    from_rule=rule.id,
                    is_match=False,
                ))
    
    # Create traceability links for NEW apply elements
    # (Apply elements bound via backward links already have their traceability)
    new_trace_links: set[SymTraceLink] = set()
    trace_counter = 0
    
    for apply_elem in rule.apply_elements:
        if apply_elem.id in apply_elem_to_pc_vertex:
            # Already bound - traceability exists
            continue
        
        apply_vertex_id = apply_elem_vertex_map[apply_elem.id]
        
        for match_elem in rule.match_elements:
            match_vertex_id = match_elem_vertex_map[match_elem.id]
            new_trace_links.add(SymTraceLink(
                id=f"{prefix}_tr_{trace_counter}",
                apply_vertex=apply_vertex_id,
                match_vertex=match_vertex_id,
                from_rule=rule.id,
            ))
            trace_counter += 1
    
    # Collect attribute constraints from the rule
    new_constraints: list[AttributeConstraint] = []
    
    for match_elem in rule.match_elements:
        if match_elem.where_clause is not None:
            new_constraints.append(AttributeConstraint(
                expr=match_elem.where_clause,
                source="match",
                rule_id=rule.id,
            ))
    
    if rule.guard is not None:
        new_constraints.append(AttributeConstraint(
            expr=rule.guard,
            source="guard",
            rule_id=rule.id,
        ))
    
    return PathCondition(
        vertices=pc.vertices | frozenset(new_match_vertices) | frozenset(new_apply_vertices),
        edges=pc.edges | frozenset(new_match_edges) | frozenset(new_apply_edges),
        trace_links=pc.trace_links | frozenset(new_trace_links),
        rule_copies=pc.rule_copies | {rule.id},
        layer_index=pc.layer_index,
        theta_attr=pc.theta_attr + tuple(new_constraints),
    )


def advance_layer(pc: PathCondition) -> PathCondition:
    """Advance path condition to next layer."""
    return PathCondition(
        vertices=pc.vertices,
        edges=pc.edges,
        trace_links=pc.trace_links,
        rule_copies=pc.rule_copies,
        layer_index=pc.layer_index + 1,
        theta_attr=pc.theta_attr,
    )


# -----------------------------------------------------------------------------
# Backward Link Dependency Checking
# -----------------------------------------------------------------------------

def check_backward_dependencies(
    pc: PathCondition,
    rule: Rule,
) -> tuple[bool, bool, set[str]]:
    """
    Legacy API: Check if rule's backward link dependencies are satisfied.
    
    Returns:
      - (can_execute, must_execute, match_locations)
      
    NOTE: For multi-location matching, use find_all_match_locations() instead.
    This function is kept for backward compatibility.
    """
    result = find_all_match_locations(pc, rule)
    
    # Convert to legacy format
    match_locs = set()
    for loc in result.locations:
        for binding in loc.bindings:
            match_locs.add(binding.pc_match_vertex_id)
    
    return result.can_execute, result.must_execute_at_all, match_locs


def find_all_match_locations(
    pc: PathCondition,
    rule: Rule,
) -> MatchResult:
    """
    Find all valid matching locations for a rule in a path condition.
    
    Implements multi-location matching from Lucio2014 Section 4.4:
      - Enumerates ALL ways backward links can bind to existing trace links
      - Each valid combination of bindings forms a MatchLocation
      - Returns MatchResult with all locations and execution semantics
    
    Cases (from Lucio2014):
      1. No backward links: Rule may or may not fire (partial, 0 locations)
      2. Backward links unsatisfied: Rule cannot fire (can_execute=False)
      3. Partial match: Rule may fire at each location independently
      4. Total match: Rule must fire at all locations
    
    See: dsltrans.tex Definition 19-24
    """
    # Check for attribute constraints
    has_guard = rule.guard is not None
    has_where_clauses = any(me.where_clause is not None for me in rule.match_elements)
    has_attribute_constraints = has_guard or has_where_clauses
    
    # Check if all match elements are covered by backward links
    all_match_ids = frozenset(me.id for me in rule.match_elements)
    constrained_match_ids = rule.backward_link_match_elements
    has_free_elements = not (constrained_match_ids >= all_match_ids)
    
    if not rule.has_backward_links:
        # Case 1: No dependencies - rule may or may not fire
        # This is a "partial" case with no specific locations
        return MatchResult(
            can_execute=True,
            locations=(),
            has_free_elements=True,  # All elements are free
            has_attribute_constraints=has_attribute_constraints,
        )
    
    # Find all trace links that could satisfy each backward link
    # backward_link -> list of matching trace links
    backward_link_candidates: dict[tuple[ElementId, ElementId], list[SymTraceLink]] = {}
    
    for bl in rule.backward_links:
        match_elem = rule.match_element_by_id.get(bl.match_element)
        apply_elem = rule.apply_element_by_id.get(bl.apply_element)
        if not match_elem or not apply_elem:
            continue
        
        bl_key = (bl.match_element, bl.apply_element)
        candidates = []
        
        for trace_link in pc.trace_links:
            apply_v = pc.get_vertex(trace_link.apply_vertex)
            match_v = pc.get_vertex(trace_link.match_vertex)
            if apply_v and match_v:
                # Check type compatibility
                if (apply_v.class_type == apply_elem.class_type and
                    match_v.class_type == match_elem.class_type):
                    candidates.append(trace_link)
        
        backward_link_candidates[bl_key] = candidates
    
    # Check if any backward link has no candidates (unsatisfied)
    if not backward_link_candidates:
        # No backward links to check (shouldn't happen if has_backward_links is True)
        return MatchResult(
            can_execute=True,
            locations=(),
            has_free_elements=has_free_elements,
            has_attribute_constraints=has_attribute_constraints,
        )
    
    for bl_key, candidates in backward_link_candidates.items():
        if not candidates:
            # Case 2: Unsatisfied - at least one backward link has no match
            return MatchResult(
                can_execute=False,
                locations=(),
                has_free_elements=has_free_elements,
                has_attribute_constraints=has_attribute_constraints,
            )
    
    # Generate all valid combinations of bindings (Cartesian product)
    # Each combination is one MatchLocation
    all_locations = _enumerate_match_locations(
        rule, 
        backward_link_candidates,
        has_free_elements,
    )
    
    return MatchResult(
        can_execute=True,
        locations=tuple(all_locations),
        has_free_elements=has_free_elements,
        has_attribute_constraints=has_attribute_constraints,
    )


def _enumerate_match_locations(
    rule: Rule,
    backward_link_candidates: dict[tuple[ElementId, ElementId], list[SymTraceLink]],
    has_free_elements: bool,
) -> list[MatchLocation]:
    """
    Enumerate all valid matching locations via Cartesian product of candidates.
    
    For N backward links with candidate counts [c1, c2, ..., cN],
    generates up to c1 * c2 * ... * cN locations.
    """
    from itertools import product
    
    if not backward_link_candidates:
        return []
    
    # Prepare for Cartesian product
    bl_keys = list(backward_link_candidates.keys())
    candidate_lists = [backward_link_candidates[k] for k in bl_keys]
    
    locations = []
    
    for combo in product(*candidate_lists):
        # combo is a tuple of SymTraceLink, one for each backward link
        bindings = []
        
        for i, trace_link in enumerate(combo):
            match_elem_id, apply_elem_id = bl_keys[i]
            bindings.append(BackwardBinding(
                backward_link_match_elem=match_elem_id,
                backward_link_apply_elem=apply_elem_id,
                pc_trace_link_id=trace_link.id,
                pc_apply_vertex_id=trace_link.apply_vertex,
                pc_match_vertex_id=trace_link.match_vertex,
            ))
        
        # Check for consistency: same rule match element should bind to same PC vertex
        # (This handles rules with multiple backward links to the same match element)
        if _is_consistent_binding(bindings):
            locations.append(MatchLocation(
                bindings=tuple(bindings),
                is_total=not has_free_elements,
            ))
    
    return locations


def _is_consistent_binding(bindings: list[BackwardBinding]) -> bool:
    """
    Check that bindings are consistent.
    
    If two backward links reference the same rule element,
    they must bind to the same PC vertex.
    """
    match_elem_to_pc_vertex: dict[ElementId, str] = {}
    apply_elem_to_pc_vertex: dict[ElementId, str] = {}
    
    for b in bindings:
        # Check match element consistency
        if b.backward_link_match_elem in match_elem_to_pc_vertex:
            if match_elem_to_pc_vertex[b.backward_link_match_elem] != b.pc_match_vertex_id:
                return False
        else:
            match_elem_to_pc_vertex[b.backward_link_match_elem] = b.pc_match_vertex_id
        
        # Check apply element consistency
        if b.backward_link_apply_elem in apply_elem_to_pc_vertex:
            if apply_elem_to_pc_vertex[b.backward_link_apply_elem] != b.pc_apply_vertex_id:
                return False
        else:
            apply_elem_to_pc_vertex[b.backward_link_apply_elem] = b.pc_apply_vertex_id
    
    return True


# -----------------------------------------------------------------------------
# Subsumption (Obligation O2)
# -----------------------------------------------------------------------------

def subsumes(pc1: PathCondition, pc2: PathCondition) -> bool:
    """
    Check if pc1 subsumes pc2 (pc1 ⊑_op pc2).
    
    Subsumption holds iff:
      - Same rule sets
      - Isomorphic structures
      - Constraint entailment: Θ_attr(pc2) ⊨ Θ_attr(pc1)
        (pc1 is more abstract, has fewer/weaker constraints)
    
    Since we abstract over rule execution count, two PCs with the same
    rule set represent the same executions.
    
    See: dsltrans.tex Definition 22 (Operational Subsumption)
    """
    # Same rule sets required
    if pc1.rule_copies != pc2.rule_copies:
        return False
    
    # Same layer
    if pc1.layer_index != pc2.layer_index:
        return False
    
    # For simple case: exact equality (canonical hash check)
    # This includes theta_attr in the hash comparison
    # For full entailment checking, SMT would be needed
    return pc1.canonical_hash == pc2.canonical_hash


def are_isomorphic(pc1: PathCondition, pc2: PathCondition) -> bool:
    """
    Check if two path conditions are isomorphic.
    
    Used for symmetry reduction optimization.
    """
    return pc1.canonical_hash == pc2.canonical_hash
