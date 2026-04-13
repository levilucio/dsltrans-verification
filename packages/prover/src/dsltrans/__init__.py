"""
DSLTrans Symbolic Execution Engine - Kernel Instantiation

Kernel mapping for DSLTrans model transformations:
  - U (symbolic universe): V_sym ∪ E_sym ∪ A_sym (symbolic vertices, edges, attributes)
  - S (structure): ⟨Match, Apply, Adj, Trace, RuleCopies, ℓ⟩ (path condition structure)
  - Θ (constraints): Θ_typing ∪ Θ_structural ∪ Θ_attr (typing, structural, attribute constraints)

Key abstraction: Rule execution count → presence/absence (0 vs ≥1)
This ensures finite path condition set: |PC| ≤ 2^|rules|

See: dsltrans.tex for the mathematical instantiation.
"""

from .model import (
    Metamodel,
    Class,
    Association,
    Transformation,
    Layer,
    Rule,
    MatchElement,
    ApplyElement,
    MatchLink,
    ApplyLink,
    BackwardLink,
    # Expression AST types (algebraic data types)
    Expr,
    IntLit,
    BoolLit,
    StringLit,
    ListLit,
    PairLit,
    VarRef,
    AttrRef,
    BinOp,
    UnaryOp,
    FuncCall,
    # Attribute types and constraints
    AttrType,
    AttributeConstraint,
    AttributeBinding,
)

from .properties import CheckMode

from .parser import parse_dsltrans
from .abstraction import (
    synthesize_abstract_spec,
    synthesize_abstract_spec_for_property,
    make_default_abstraction_policy,
    AbstractionPolicy,
    AttributeOverride,
    AbstractionResult,
)
from .spec_writer import render_spec

from .smt_direct import (
    verify_direct,
    SMTDirectConfig,
    DirectVerificationResult,
    PropertyVerificationResult,
    SMTModelEncoder,
    SMTRuleEncoder,
    SMTPropertyEncoder,
    SMTDirectVerifier,
    CheckResult,
    ExprToZ3,
)

from .cutoff import (
    check_fragment,
    compute_cutoff_bound,
    compute_cutoff_bound_detailed,
    FragmentViolation,
    CutoffBoundDetails,
)

from .concrete_model import ConcreteModel, ConcreteNode, ConcreteEdge, TraceLink
from .runtime_engine import execute_transformation, ExecutionStats
from .xmi_io import load_xmi_model, save_xmi_model
from .ecore_io import load_ecore_model, check_metamodel_consistency, EcoreModel, EcoreReference

__all__ = [
    # Model
    "Metamodel",
    "Class", 
    "Association",
    "Transformation",
    "Layer",
    "Rule",
    "MatchElement",
    "ApplyElement",
    "MatchLink",
    "ApplyLink",
    "BackwardLink",
    # Expression AST types (algebraic data types)
    "Expr",
    "IntLit",
    "BoolLit",
    "StringLit",
    "ListLit",
    "PairLit",
    "VarRef",
    "AttrRef",
    "BinOp",
    "UnaryOp",
    "FuncCall",
    # Attribute types and constraints
    "AttrType",
    "AttributeConstraint",
    "AttributeBinding",
    "CheckMode",
    "CheckResult",
    "ExprToZ3",
    # Parsing
    "parse_dsltrans",
    "synthesize_abstract_spec",
    "synthesize_abstract_spec_for_property",
    "make_default_abstraction_policy",
    "AbstractionPolicy",
    "AttributeOverride",
    "AbstractionResult",
    "render_spec",
    # SMT Direct Verification
    "verify_direct",
    "SMTDirectConfig",
    "DirectVerificationResult",
    "PropertyVerificationResult",
    "SMTModelEncoder",
    "SMTRuleEncoder",
    "SMTPropertyEncoder",
    "SMTDirectVerifier",
    # Cutoff theorem
    "check_fragment",
    "compute_cutoff_bound",
    "compute_cutoff_bound_detailed",
    "FragmentViolation",
    "CutoffBoundDetails",
    # Runtime execution
    "ConcreteModel",
    "ConcreteNode",
    "ConcreteEdge",
    "TraceLink",
    "execute_transformation",
    "ExecutionStats",
    "load_xmi_model",
    "save_xmi_model",
    # Ecore checks
    "load_ecore_model",
    "check_metamodel_consistency",
    "EcoreModel",
    "EcoreReference",
]
