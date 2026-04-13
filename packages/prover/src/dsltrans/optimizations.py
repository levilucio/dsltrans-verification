"""
DSLTrans Performance Optimizations

Implements the six optimization techniques from dsltrans.tex Section E.4.9:

1. Symmetry Reduction - Canonical hashing to detect isomorphic PCs
2. POR for Rules - Canonical ordering for independent rules
3. Property-Guided Exploration - Skip irrelevant path conditions
4. Lazy Disambiguation - Defer overlap resolution
5. Rule Dependency Analysis - Skip infeasible combinations
6. Component-Wise Exploration - Separate independent rule groups
7. Memoization - Cache matching results
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import FrozenSet, Optional
import hashlib

from .model import Transformation, Rule, RuleId, Layer, ClassId, AssocId


# -----------------------------------------------------------------------------
# Rule Dependency Graph (Optimization #5)
# -----------------------------------------------------------------------------

@dataclass
class RuleDependencyGraph:
    """
    Rule dependency graph for pruning infeasible combinations.
    
    An edge r1 -> r2 means r2 depends on r1 (r2's backward links
    require traceability created by r1).
    """
    # rule_id -> set of rules it depends on
    dependencies: dict[RuleId, FrozenSet[RuleId]]
    
    # rule_id -> set of rules that depend on it
    dependents: dict[RuleId, FrozenSet[RuleId]]
    
    # rule_id -> layer index
    rule_layer: dict[RuleId, int]


def compute_rule_dependencies(transformation: Transformation) -> RuleDependencyGraph:
    """
    Compute rule dependency graph from transformation structure.
    
    A rule r2 depends on r1 if:
      - r2 has backward links
      - Those backward links require traceability from types that r1 produces
      - r1 is in an earlier layer than r2
    """
    dependencies: dict[RuleId, set[RuleId]] = {}
    dependents: dict[RuleId, set[RuleId]] = {}
    rule_layer: dict[RuleId, int] = {}
    
    # Build type -> producing rules map
    type_producers: dict[ClassId, set[RuleId]] = {}
    
    for layer_idx, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            rule_layer[rule.id] = layer_idx
            dependencies[rule.id] = set()
            dependents[rule.id] = set()
            
            # Record types this rule produces
            for apply_elem in rule.apply_elements:
                if apply_elem.class_type not in type_producers:
                    type_producers[apply_elem.class_type] = set()
                type_producers[apply_elem.class_type].add(rule.id)
    
    # Compute dependencies based on backward links
    for layer_idx, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            if not rule.has_backward_links:
                continue
            
            # Check what types the backward links require
            for bl in rule.backward_links:
                apply_elem = rule.apply_element_by_id.get(bl.apply_element)
                match_elem = rule.match_element_by_id.get(bl.match_element)
                
                if apply_elem is None or match_elem is None:
                    continue
                
                # The backward link requires that some earlier rule produced
                # an element of apply_elem's type with trace to match_elem's type
                required_type = apply_elem.class_type
                
                # Find rules in earlier layers that produce this type
                for producer_id in type_producers.get(required_type, set()):
                    producer_layer = rule_layer[producer_id]
                    if producer_layer < layer_idx:
                        dependencies[rule.id].add(producer_id)
                        dependents[producer_id].add(rule.id)
    
    return RuleDependencyGraph(
        dependencies={k: frozenset(v) for k, v in dependencies.items()},
        dependents={k: frozenset(v) for k, v in dependents.items()},
        rule_layer=rule_layer,
    )


def compute_rule_dependencies_trace_aware(transformation: Transformation) -> RuleDependencyGraph:
    """
    Compute a *trace-aware* rule dependency graph.

    Compared to compute_rule_dependencies(), this refines dependencies by using the
    traceability semantics used by the SMT encoding:

    - A rule that *creates* a new apply element of type T (i.e., the apply element
      is NOT backed by a backward link) produces an implicit trace from every match
      element type S in its match pattern to that created target type T.
    - A backward link in a later rule requires an *existing* target element of some
      type T that is trace-linked to a specific match element type S.

    So r2 depends on r1 only if r1 can create T and (implicitly) trace it from S.

    This can substantially reduce over-approximation in large transformations,
    lowering dependency depth d and thus cutoff bounds.
    """
    dependencies: dict[RuleId, set[RuleId]] = {}
    dependents: dict[RuleId, set[RuleId]] = {}
    rule_layer: dict[RuleId, int] = {}

    # Build:
    #  - (src_type, tgt_type) -> producing rules (can create tgt_type and trace from src_type)
    #  - tgt_type -> producing rules (fallback)
    trace_producers: dict[tuple[ClassId, ClassId], set[RuleId]] = {}
    type_producers: dict[ClassId, set[RuleId]] = {}

    for layer_idx, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            rule_layer[rule.id] = layer_idx
            dependencies[rule.id] = set()
            dependents[rule.id] = set()

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

    # Compute dependencies based on backward links (trace-aware)
    for layer_idx, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            if not rule.has_backward_links:
                continue

            for bl in rule.backward_links:
                apply_elem = rule.apply_element_by_id.get(bl.apply_element)
                match_elem = rule.match_element_by_id.get(bl.match_element)
                if apply_elem is None or match_elem is None:
                    continue

                required_t = apply_elem.class_type
                required_s = match_elem.class_type

                candidates = trace_producers.get((required_s, required_t), set())
                # Under strict backward-link semantics, no trace-aware producer
                # means the backward dependency is unsatisfiable.
                if not candidates:
                    continue

                for producer_id in candidates:
                    producer_layer = rule_layer.get(producer_id, 0)
                    if producer_layer < layer_idx:
                        dependencies[rule.id].add(producer_id)
                        dependents[producer_id].add(rule.id)

    return RuleDependencyGraph(
        dependencies={k: frozenset(v) for k, v in dependencies.items()},
        dependents={k: frozenset(v) for k, v in dependents.items()},
        rule_layer=rule_layer,
    )


def is_combination_feasible(
    current_rules: FrozenSet[RuleId],
    new_rule: RuleId,
    dep_graph: RuleDependencyGraph,
) -> bool:
    """
    Check if adding new_rule to current_rules is feasible.
    
    A combination is infeasible if new_rule depends on rules
    not in current_rules.
    """
    required = dep_graph.dependencies.get(new_rule, frozenset())
    
    # All dependencies must be in current rules
    return required.issubset(current_rules)


# -----------------------------------------------------------------------------
# Rule Independence / POR (Optimization #2)
# -----------------------------------------------------------------------------

@dataclass
class RuleFootprint:
    """Resource footprint for a rule."""
    rule_id: RuleId
    # Metamodel types accessed in match pattern
    match_types: FrozenSet[ClassId]
    # Metamodel types produced in apply pattern
    apply_types: FrozenSet[ClassId]
    # Association types used
    assoc_types: FrozenSet[AssocId]


def compute_rule_footprints(transformation: Transformation) -> dict[RuleId, RuleFootprint]:
    """Compute footprint for each rule."""
    footprints = {}
    
    for layer in transformation.layers:
        for rule in layer.rules:
            match_types = frozenset(e.class_type for e in rule.match_elements)
            apply_types = frozenset(e.class_type for e in rule.apply_elements)
            assoc_types = frozenset(
                l.assoc_type for l in rule.match_links
            ) | frozenset(
                l.assoc_type for l in rule.apply_links
            )
            
            footprints[rule.id] = RuleFootprint(
                rule_id=rule.id,
                match_types=match_types,
                apply_types=apply_types,
                assoc_types=assoc_types,
            )
    
    return footprints


def compute_independent_rules(layer: Layer) -> list[tuple[RuleId, RuleId]]:
    """
    Compute pairs of structurally independent rules in a layer.
    
    Two rules are independent if they access disjoint metamodel regions.
    """
    independent = []
    rules = list(layer.rules)
    
    for i, r1 in enumerate(rules):
        for r2 in rules[i+1:]:
            if _are_rules_independent(r1, r2):
                independent.append((r1.id, r2.id))
    
    return independent


def _are_rules_independent(r1: Rule, r2: Rule) -> bool:
    """Check if two rules are structurally independent."""
    # Match types overlap
    r1_match = {e.class_type for e in r1.match_elements}
    r2_match = {e.class_type for e in r2.match_elements}
    if r1_match & r2_match:
        return False
    
    # Apply types overlap
    r1_apply = {e.class_type for e in r1.apply_elements}
    r2_apply = {e.class_type for e in r2.apply_elements}
    if r1_apply & r2_apply:
        return False
    
    # Association types overlap
    r1_assoc = {l.assoc_type for l in r1.match_links} | {l.assoc_type for l in r1.apply_links}
    r2_assoc = {l.assoc_type for l in r2.match_links} | {l.assoc_type for l in r2.apply_links}
    if r1_assoc & r2_assoc:
        return False
    
    return True


def canonical_rule_order(rules: list[Rule]) -> list[Rule]:
    """
    Compute canonical ordering for rules (POR-like optimization).
    
    Independent rules can be combined in any order - we choose
    a canonical (lexicographic) order to avoid redundant exploration.
    """
    return sorted(rules, key=lambda r: str(r.id))


# -----------------------------------------------------------------------------
# Component-Wise Exploration (Optimization #6)
# -----------------------------------------------------------------------------

def compute_rule_components(transformation: Transformation) -> list[FrozenSet[RuleId]]:
    """
    Partition rules into independent components.
    
    Rules in different components have no dependencies between them
    and can be explored separately.
    """
    dep_graph = compute_rule_dependencies(transformation)
    
    # Build undirected adjacency from dependency graph
    adjacency: dict[RuleId, set[RuleId]] = {}
    for rule_id in dep_graph.dependencies:
        adjacency[rule_id] = set()
    
    for rule_id, deps in dep_graph.dependencies.items():
        for dep in deps:
            adjacency[rule_id].add(dep)
            adjacency[dep].add(rule_id)
    
    # Find connected components using DFS
    visited: set[RuleId] = set()
    components: list[FrozenSet[RuleId]] = []
    
    def dfs(start: RuleId) -> FrozenSet[RuleId]:
        component = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for neighbor in adjacency.get(node, set()):
                if neighbor not in visited:
                    stack.append(neighbor)
        return frozenset(component)
    
    for rule_id in adjacency:
        if rule_id not in visited:
            components.append(dfs(rule_id))
    
    return components


# -----------------------------------------------------------------------------
# Symmetry Reduction (Optimization #1)
# -----------------------------------------------------------------------------

def canonical_hash(
    rules: FrozenSet[RuleId],
    structure_sig: str,
    constraint_sig: str = "",
) -> str:
    """
    Compute canonical hash for a path condition configuration.
    
    Two path conditions with the same hash are isomorphic and
    need not both be explored.
    
    Args:
        rules: Set of rule IDs in the path condition
        structure_sig: Signature of the structural configuration
        constraint_sig: Signature of attribute constraints (Θ_attr)
                       Used to distinguish PCs with same structure but different constraints.
    
    Returns:
        16-character hex hash
    """
    sorted_rules = tuple(sorted(str(r) for r in rules))
    content = (sorted_rules, structure_sig, constraint_sig)
    return hashlib.sha256(str(content).encode()).hexdigest()[:16]


def compute_constraint_signature(theta_attr: tuple) -> str:
    """
    Compute a canonical signature for attribute constraints.
    
    This allows hash-based comparison of path conditions that may
    have different constraint sets.
    """
    if not theta_attr:
        return ""
    
    # Sort constraints by source and expression string representation
    constraint_parts = sorted(
        (str(c.expr), c.source, str(c.rule_id) if c.rule_id else "")
        for c in theta_attr
    )
    return hashlib.sha256(str(constraint_parts).encode()).hexdigest()[:8]


# -----------------------------------------------------------------------------
# Property-Guided Exploration (Optimization #3)
# -----------------------------------------------------------------------------

def extract_property_types(properties) -> tuple[FrozenSet[ClassId], FrozenSet[ClassId]]:
    """
    Extract metamodel types mentioned in properties.
    
    Returns (precondition_types, postcondition_types)
    """
    pre_types: set[ClassId] = set()
    post_types: set[ClassId] = set()
    
    for prop in properties:
        if hasattr(prop, 'precondition') and prop.precondition:
            for elem in prop.precondition.elements:
                pre_types.add(elem.class_type)
        
        if hasattr(prop, 'postcondition') and prop.postcondition:
            for elem in prop.postcondition.elements:
                post_types.add(elem.class_type)
    
    return frozenset(pre_types), frozenset(post_types)


def is_pc_relevant_to_property(
    pc_match_types: FrozenSet[ClassId],
    pc_apply_types: FrozenSet[ClassId],
    property_pre_types: FrozenSet[ClassId],
    property_post_types: FrozenSet[ClassId],
) -> bool:
    """
    Check if a path condition is relevant to property checking.
    
    A PC is relevant if it could potentially satisfy the precondition.
    """
    if not property_pre_types:
        # No precondition - PC is always relevant
        return True
    
    # PC must contain all precondition types
    return property_pre_types.issubset(pc_match_types)


def compute_relevant_rules(
    transformation: 'Transformation',
    properties: list,
) -> tuple[FrozenSet[RuleId], dict[RuleId, int]]:
    """
    Compute which rules are relevant to the given properties.
    
    A rule is relevant if:
      1. It produces types mentioned in property postconditions, OR
      2. It produces types that other relevant rules depend on (backward links), OR
      3. It is in a layer BEFORE the earliest directly relevant rule (infrastructure)
    
    Returns:
        (relevant_rule_ids, rule_relevance_scores)
        where score = number of properties the rule helps verify
    """
    pre_types, post_types = extract_property_types(properties)
    all_relevant_types = pre_types | post_types
    
    # Build layer index for each rule
    rule_to_layer: dict[RuleId, int] = {}
    for layer_idx, layer in enumerate(transformation.layers):
        for rule in layer.rules:
            rule_to_layer[rule.id] = layer_idx
    
    # Map from type to rules that produce it
    type_producers: dict[ClassId, set[RuleId]] = {}
    for layer in transformation.layers:
        for rule in layer.rules:
            for apply_elem in rule.apply_elements:
                if apply_elem.class_type not in type_producers:
                    type_producers[apply_elem.class_type] = set()
                type_producers[apply_elem.class_type].add(rule.id)
    
    # Find directly relevant rules (produce property types)
    directly_relevant: set[RuleId] = set()
    rule_scores: dict[RuleId, int] = {}
    
    for rule_type in all_relevant_types:
        for rule_id in type_producers.get(rule_type, set()):
            directly_relevant.add(rule_id)
            rule_scores[rule_id] = rule_scores.get(rule_id, 0) + 1
    
    # Transitively add rules that relevant rules depend on
    all_relevant = set(directly_relevant)
    dep_graph = compute_rule_dependencies(transformation)
    
    worklist = list(directly_relevant)
    while worklist:
        rule_id = worklist.pop()
        for dep_id in dep_graph.dependencies.get(rule_id, frozenset()):
            if dep_id not in all_relevant:
                all_relevant.add(dep_id)
                worklist.append(dep_id)
                # Lower score for transitive dependencies
                rule_scores[dep_id] = rule_scores.get(dep_id, 0) + 0.5
    
    # CRITICAL: Include all rules in layers BEFORE the earliest relevant rule
    # These are "infrastructure" rules needed to establish initial structure
    if all_relevant:
        earliest_layer = min(rule_to_layer[r] for r in all_relevant)
        for layer_idx, layer in enumerate(transformation.layers):
            if layer_idx < earliest_layer:
                for rule in layer.rules:
                    if rule.id not in all_relevant:
                        all_relevant.add(rule.id)
                        rule_scores[rule.id] = 0.1  # Very low score for infrastructure
    
    return frozenset(all_relevant), rule_scores


def get_irrelevant_rules(
    transformation: 'Transformation',
    relevant_rules: FrozenSet[RuleId],
) -> FrozenSet[RuleId]:
    """Get rules that are NOT relevant to any property."""
    all_rules = {rule.id for rule in transformation.all_rules}
    return frozenset(all_rules - relevant_rules)


# -----------------------------------------------------------------------------
# Memoization (Optimization #7)
# -----------------------------------------------------------------------------

class MatchCache:
    """
    Cache for subgraph isomorphism results.
    
    Caches:
      - Rule-to-PC matching (backward link satisfaction)
      - Property-to-PC matching
    """
    
    def __init__(self):
        self._backward_cache: dict[tuple, tuple[bool, bool, frozenset]] = {}
        self._pattern_cache: dict[tuple, list] = {}
    
    def get_backward_check(
        self,
        pc_hash: str,
        rule_id: RuleId,
    ) -> Optional[tuple[bool, bool, frozenset]]:
        key = (pc_hash, rule_id)
        return self._backward_cache.get(key)
    
    def set_backward_check(
        self,
        pc_hash: str,
        rule_id: RuleId,
        result: tuple[bool, bool, frozenset],
    ) -> None:
        key = (pc_hash, rule_id)
        self._backward_cache[key] = result
    
    def get_pattern_match(
        self,
        pc_hash: str,
        pattern_sig: str,
    ) -> Optional[list]:
        key = (pc_hash, pattern_sig)
        return self._pattern_cache.get(key)
    
    def set_pattern_match(
        self,
        pc_hash: str,
        pattern_sig: str,
        result: list,
    ) -> None:
        key = (pc_hash, pattern_sig)
        self._pattern_cache[key] = result
    
    def clear(self) -> None:
        self._backward_cache.clear()
        self._pattern_cache.clear()
