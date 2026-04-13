"""
DSLTrans Model - Core Data Structures

Implements the formal definitions from the DSLTrans appendix:
  - Definition: Typed Graph
  - Definition: Metamodel
  - Definition: Model
  - Definition: Transformation Rule
  - Definition: Layer and Model Transformation

Kernel mapping:
  - U = V_sym ∪ E_sym ∪ A_sym (symbolic entities)
  - S = ⟨Match, Apply, Adj, Trace, RuleCopies, ℓ⟩ (structure)
  - Θ = Θ_typing ∪ Θ_structural ∪ Θ_attr (constraints)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import NewType, FrozenSet, Optional
from functools import cached_property

# -----------------------------------------------------------------------------
# Type Identifiers
# -----------------------------------------------------------------------------

ClassId = NewType("ClassId", str)
AssocId = NewType("AssocId", str)
ElementId = NewType("ElementId", str)
RuleId = NewType("RuleId", str)
LayerId = NewType("LayerId", str)


class MatchType(Enum):
    """Match element binding type."""
    ANY = auto()     # Binds to all matching instances
    EXISTS = auto()  # Binds to one (deterministic) instance


class LinkKind(Enum):
    """Link kind for match patterns."""
    DIRECT = auto()    # Explicit association match
    INDIRECT = auto()  # Transitive containment path


class AttrType(Enum):
    """
    Algebraic data types for attribute expressions.
    
    Supports: Int, Bool, String, List[T], Pair[T1,T2]
    """
    INT = "Int"
    BOOL = "Bool"
    STRING = "String"
    LIST = "List"      # Parameterized: List[Int], List[Bool], etc.
    PAIR = "Pair"      # Parameterized: Pair[Int, String]
    UNKNOWN = "Unknown"  # For type inference


# -----------------------------------------------------------------------------
# Expression AST for Attribute Constraints
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Expr:
    """Base class for attribute expressions."""
    pass


@dataclass(frozen=True)
class IntLit(Expr):
    """Integer literal."""
    value: int


@dataclass(frozen=True)
class BoolLit(Expr):
    """Boolean literal."""
    value: bool


@dataclass(frozen=True)
class StringLit(Expr):
    """String literal."""
    value: str


@dataclass(frozen=True)
class ListLit(Expr):
    """List literal with homogeneous element type."""
    elements: tuple[Expr, ...]
    elem_type: AttrType = AttrType.UNKNOWN


@dataclass(frozen=True)
class PairLit(Expr):
    """Pair literal (2-tuple)."""
    fst: Expr
    snd: Expr


@dataclass(frozen=True)
class VarRef(Expr):
    """Reference to a variable (element name)."""
    name: str


@dataclass(frozen=True)
class AttrRef(Expr):
    """Reference to element.attribute."""
    element: str
    attribute: str


@dataclass(frozen=True)
class BinOp(Expr):
    """Binary operation."""
    op: str  # +, -, *, /, %, ==, !=, <, <=, >, >=, &&, ||
    left: Expr
    right: Expr


@dataclass(frozen=True)
class UnaryOp(Expr):
    """Unary operation."""
    op: str  # !, -
    operand: Expr


@dataclass(frozen=True)
class FuncCall(Expr):
    """Function call expression."""
    name: str  # head, tail, append, concat, length, fst, snd, isEmpty
    args: tuple[Expr, ...]


# -----------------------------------------------------------------------------
# Attribute Constraints (Θ_attr)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class AttributeConstraint:
    """
    Single constraint in Θ_attr.
    
    Represents a boolean expression that must hold for the path condition
    to represent valid concrete executions.
    """
    expr: Expr  # Boolean expression
    source: str  # "guard", "match", "apply", "property"
    rule_id: Optional[RuleId] = None  # Source rule if applicable


@dataclass(frozen=True)
class AttributeBinding:
    """
    Attribute assignment in apply pattern.
    
    Represents: target_element.attribute = value_expression
    """
    target: AttrRef
    value: Expr


# -----------------------------------------------------------------------------
# Parameterized Type for Lists and Pairs
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ParameterizedType:
    """
    Parameterized type for List[T] and Pair[T1, T2].
    """
    base: AttrType
    params: tuple[AttrType, ...]  # e.g., (INT,) for List[Int], (INT, STRING) for Pair[Int, String]


# -----------------------------------------------------------------------------
# Metamodel Definition
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Attribute:
    """Attribute definition in a class."""
    name: str
    type: str  # "Int", "String", "Bool", "Real", or enum type name
    default: Optional[str] = None
    # Finite-domain metadata (for tractable, complete attribute proofs under R5)
    int_range: Optional[tuple[int, int]] = None
    string_vocab: tuple[str, ...] = ()


@dataclass(frozen=True)
class Class:
    """Metamodel class (vertex type)."""
    id: ClassId
    name: str
    is_abstract: bool = False
    parent: Optional[ClassId] = None  # Inheritance
    attributes: tuple[Attribute, ...] = ()


@dataclass(frozen=True)
class Association:
    """Metamodel association (edge type)."""
    id: AssocId
    name: str
    source_class: ClassId
    target_class: ClassId
    source_mult: tuple[int, Optional[int]]  # (min, max) where None = *
    target_mult: tuple[int, Optional[int]]
    is_containment: bool = False


@dataclass(frozen=True)
class EnumType:
    """Finite enum type definition in a metamodel."""
    name: str
    literals: tuple[str, ...]


@dataclass(frozen=True)
class Metamodel:
    """
    Metamodel definition.
    
    A metamodel is a typed graph schema defining:
      - Classes (vertex types) with optional inheritance
      - Associations (edge types) with multiplicities
      - Containment relationships
    """
    name: str
    classes: tuple[Class, ...]
    associations: tuple[Association, ...]
    enums: tuple[EnumType, ...] = ()
    
    def __post_init__(self) -> None:
        # Validate references
        class_ids = {c.id for c in self.classes}
        for assoc in self.associations:
            if assoc.source_class not in class_ids:
                raise ValueError(f"Association {assoc.name} references unknown source class {assoc.source_class}")
            if assoc.target_class not in class_ids:
                raise ValueError(f"Association {assoc.name} references unknown target class {assoc.target_class}")
    
    @cached_property
    def class_by_id(self) -> dict[ClassId, Class]:
        return {c.id: c for c in self.classes}
    
    @cached_property
    def class_by_name(self) -> dict[str, Class]:
        return {c.name: c for c in self.classes}
    
    @cached_property
    def assoc_by_id(self) -> dict[AssocId, Association]:
        return {a.id: a for a in self.associations}
    
    @cached_property
    def assoc_by_name(self) -> dict[str, Association]:
        return {a.name: a for a in self.associations}

    @cached_property
    def enum_by_name(self) -> dict[str, EnumType]:
        return {e.name: e for e in self.enums}
    
    def get_subtypes(self, class_id: ClassId) -> FrozenSet[ClassId]:
        """Get all subtypes of a class (including itself)."""
        result = {class_id}
        for c in self.classes:
            if c.parent == class_id:
                result.update(self.get_subtypes(c.id))
        return frozenset(result)


# -----------------------------------------------------------------------------
# Rule Definition
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchElement:
    """
    Match element in a rule's match pattern.
    
    Variables typed by source metamodel classes that bind to
    instances in the input model.
    """
    id: ElementId
    name: str
    class_type: ClassId
    match_type: MatchType = MatchType.ANY
    attribute_conditions: tuple[str, ...] = ()  # Legacy: "attr op value" strings
    where_clause: Optional[Expr] = None  # NEW: Typed where expression


@dataclass(frozen=True)
class MatchLink:
    """
    Match link between match elements.
    
    Direct links match explicit associations.
    Indirect links match transitive containment paths.
    """
    id: ElementId
    name: str
    assoc_type: AssocId
    source: ElementId  # Match element id
    target: ElementId  # Match element id
    kind: LinkKind = LinkKind.DIRECT


@dataclass(frozen=True)
class ApplyElement:
    """
    Apply element in a rule's apply pattern.
    
    Variables typed by target metamodel classes that create
    instances in the output model.
    """
    id: ElementId
    name: str
    class_type: ClassId
    attribute_assignments: tuple[str, ...] = ()  # Legacy: "attr := expr" strings
    attribute_bindings: tuple[AttributeBinding, ...] = ()  # NEW: Typed bindings


@dataclass(frozen=True)
class ApplyLink:
    """
    Apply link between apply elements.
    
    Creates associations in the output model.
    """
    id: ElementId
    name: str
    assoc_type: AssocId
    source: ElementId  # Apply element id
    target: ElementId  # Apply element id


@dataclass(frozen=True)
class BackwardLink:
    """
    Backward link from apply element to match element.
    
    Expresses dependency on traceability links created by
    prior layers. Used to connect output elements to their
    corresponding input elements.
    """
    apply_element: ElementId
    match_element: ElementId


@dataclass(frozen=True)
class Rule:
    """
    DSLTrans transformation rule.
    
    A rule is a pair (MatchModel, ApplyModel) where:
      - MatchModel: Non-empty pattern over source metamodel
      - ApplyModel: Non-empty pattern over target metamodel
      - BackwardLinks: Dependencies on prior rule executions
      - Guard: Optional boolean expression constraining rule applicability
    """
    id: RuleId
    name: str
    match_elements: tuple[MatchElement, ...]
    match_links: tuple[MatchLink, ...]
    apply_elements: tuple[ApplyElement, ...]
    apply_links: tuple[ApplyLink, ...]
    backward_links: tuple[BackwardLink, ...]
    guard: Optional[Expr] = None  # NEW: Guard expression over match elements
    
    def __post_init__(self) -> None:
        if not self.match_elements:
            raise ValueError(f"Rule {self.name} has empty match pattern")
        if not self.apply_elements:
            raise ValueError(f"Rule {self.name} has empty apply pattern")
    
    @cached_property
    def match_element_by_id(self) -> dict[ElementId, MatchElement]:
        return {e.id: e for e in self.match_elements}
    
    @cached_property
    def apply_element_by_id(self) -> dict[ElementId, ApplyElement]:
        return {e.id: e for e in self.apply_elements}
    
    @cached_property
    def has_backward_links(self) -> bool:
        return len(self.backward_links) > 0
    
    @cached_property
    def backward_link_match_elements(self) -> FrozenSet[ElementId]:
        """Match elements referenced by backward links."""
        return frozenset(bl.match_element for bl in self.backward_links)
    
    @cached_property
    def backward_link_apply_elements(self) -> FrozenSet[ElementId]:
        """Apply elements connected by backward links."""
        return frozenset(bl.apply_element for bl in self.backward_links)


# -----------------------------------------------------------------------------
# Layer and Transformation Definition
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Layer:
    """
    Transformation layer.
    
    A finite set of rules that execute in non-deterministic order
    but produce deterministic results (confluence by construction).
    """
    id: LayerId
    name: str
    rules: tuple[Rule, ...]
    
    @cached_property
    def rule_by_id(self) -> dict[RuleId, Rule]:
        return {r.id: r for r in self.rules}
    
    @cached_property
    def rule_by_name(self) -> dict[str, Rule]:
        return {r.name: r for r in self.rules}


@dataclass(frozen=True)
class Transformation:
    """
    DSLTrans model transformation.
    
    A finite sequence of layers executed sequentially.
    Guarantees termination and confluence by construction.
    """
    name: str
    source_metamodel: Metamodel
    target_metamodel: Metamodel
    layers: tuple[Layer, ...]
    
    @cached_property
    def all_rules(self) -> tuple[Rule, ...]:
        """All rules across all layers."""
        return tuple(r for layer in self.layers for r in layer.rules)
    
    @cached_property
    def rule_count(self) -> int:
        return len(self.all_rules)
    
    @cached_property
    def layer_count(self) -> int:
        return len(self.layers)
    
    def get_rule_layer_index(self, rule_id: RuleId) -> int:
        """Get the layer index containing a rule."""
        for i, layer in enumerate(self.layers):
            if rule_id in layer.rule_by_id:
                return i
        raise ValueError(f"Rule {rule_id} not found in transformation")


# -----------------------------------------------------------------------------
# Property Definition
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class PreCondition:
    """Pre-condition pattern over source metamodel."""
    elements: tuple[MatchElement, ...]
    links: tuple[MatchLink, ...]
    constraint: Optional[Expr] = None  # NEW: Additional constraint on precondition


@dataclass(frozen=True)
class PostCondition:
    """Post-condition pattern over target metamodel with traceability."""
    elements: tuple[ApplyElement, ...]
    links: tuple[ApplyLink, ...]
    trace_links: tuple[tuple[ElementId, ElementId], ...]  # (post_elem, pre_elem)
    constraint: Optional[Expr] = None  # NEW: Additional constraint on postcondition


@dataclass(frozen=True)
class Property:
    """
    Transformation property (contract).
    
    States: "If Pre matches in input, then Post matches in output."
    Empty Pre means the property holds unconditionally.
    """
    id: str
    name: str
    precondition: Optional[PreCondition]
    postcondition: PostCondition


@dataclass(frozen=True)
class CompositeProperty:
    """
    Composite property built from atomic contracts.
    
    Uses propositional logic: and, or, not, implies
    """
    id: str
    name: str
    atomics: tuple[Property, ...]
    formula: str  # Propositional formula over atomic IDs
    free_var_bindings: tuple[tuple[str, str], ...] = ()  # (var_name, element_id)
