"""
DSLTrans Parser

Parses DSLTrans textual specifications into model objects.
Implements the grammar from dsltrans.tex Section E.4.2.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .lexer import Token, TokenKind, lex, LexError
from .model import (
    Metamodel, Class, Association, Attribute, EnumType,
    Transformation, Layer, Rule,
    MatchElement, MatchLink, ApplyElement, ApplyLink, BackwardLink,
    MatchType, LinkKind,
    Property, PreCondition, PostCondition, CompositeProperty,
    ClassId, AssocId, ElementId, RuleId, LayerId,
    # Expression AST types
    Expr, IntLit, BoolLit, StringLit, ListLit, PairLit,
    VarRef, AttrRef, BinOp, UnaryOp, FuncCall,
    AttributeConstraint, AttributeBinding,
)


class ParseError(ValueError):
    """Parser error with position information."""
    
    def __init__(self, msg: str, token: Token):
        super().__init__(f"Parse error at line {token.line}, col {token.col}: {msg}")
        self.token = token


@dataclass
class ParsedSpec:
    """Complete parsed specification."""
    metamodels: tuple[Metamodel, ...]
    transformations: tuple[Transformation, ...]
    properties: tuple[Property | CompositeProperty, ...]


class Parser:
    """Recursive descent parser for DSLTrans specifications."""
    
    def __init__(self, src: str):
        self.src = src
        self.tokens = list(lex(src))
        self.pos = 0
    
    def _cur(self) -> Token:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]
    
    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else self.tokens[-1]
    
    def _at(self, kind: TokenKind) -> bool:
        return self._cur().kind == kind
    
    def _at_sym(self, text: str) -> bool:
        t = self._cur()
        return t.kind == "SYM" and t.text == text
    
    def _at_kw(self, *kinds: TokenKind) -> bool:
        return self._cur().kind in kinds
    
    def _expect(self, kind: TokenKind) -> Token:
        t = self._cur()
        if t.kind != kind:
            raise ParseError(f"Expected {kind}, got {t.kind} ({t.text!r})", t)
        self.pos += 1
        return t
    
    def _expect_sym(self, text: str) -> Token:
        t = self._cur()
        if t.kind != "SYM" or t.text != text:
            raise ParseError(f"Expected symbol '{text}', got {t.text!r}", t)
        self.pos += 1
        return t
    
    def _accept_sym(self, text: str) -> bool:
        if self._at_sym(text):
            self.pos += 1
            return True
        return False
    
    def _accept_kw(self, kind: TokenKind) -> bool:
        if self._cur().kind == kind:
            self.pos += 1
            return True
        return False
    
    # -------------------------------------------------------------------------
    # Top-level parsing
    # -------------------------------------------------------------------------
    
    def parse(self) -> ParsedSpec:
        """Parse complete specification."""
        metamodels: list[Metamodel] = []
        transformations: list[Transformation] = []
        properties: list[Property | CompositeProperty] = []
        
        while not self._at("EOF"):
            if self._at_kw("KW_METAMODEL"):
                metamodels.append(self._parse_metamodel())
            elif self._at_kw("KW_TRANSFORMATION"):
                # Need metamodels first
                mm_by_name = {m.name: m for m in metamodels}
                transformations.append(self._parse_transformation(mm_by_name))
            elif self._at_kw("KW_PROPERTY"):
                properties.append(self._parse_property())
            elif self._at_kw("KW_COMPOSITE"):
                properties.append(self._parse_composite_property())
            else:
                raise ParseError(f"Unexpected token: {self._cur().text!r}", self._cur())
        
        return ParsedSpec(
            metamodels=tuple(metamodels),
            transformations=tuple(transformations),
            properties=tuple(properties),
        )
    
    # -------------------------------------------------------------------------
    # Metamodel parsing
    # -------------------------------------------------------------------------
    
    def _parse_metamodel(self) -> Metamodel:
        """Parse metamodel definition."""
        self._expect("KW_METAMODEL")
        name = self._expect("IDENT").text
        self._expect_sym("{")
        
        classes: list[Class] = []
        associations: list[Association] = []
        enums: list[EnumType] = []
        
        while not self._at_sym("}"):
            if self._at_kw("KW_ABSTRACT", "KW_CLASS"):
                classes.append(self._parse_class())
            elif self._at_kw("KW_ENUM"):
                enums.append(self._parse_enum())
            elif self._at_kw("KW_CONTAINMENT", "KW_ASSOC"):
                associations.append(self._parse_association())
            else:
                raise ParseError(
                    f"Expected class, enum, or assoc, got {self._cur().text!r}",
                    self._cur(),
                )
        
        self._expect_sym("}")
        return Metamodel(
            name=name,
            classes=tuple(classes),
            associations=tuple(associations),
            enums=tuple(enums),
        )

    def _parse_enum(self) -> EnumType:
        """Parse enum definition: enum Name { A, B, C }."""
        self._expect("KW_ENUM")
        name = self._expect("IDENT").text
        self._expect_sym("{")
        literals: list[str] = []
        while not self._at_sym("}"):
            lit = self._expect("IDENT").text
            literals.append(lit)
            self._accept_sym(",")
        self._expect_sym("}")
        if not literals:
            raise ParseError(f"Enum {name} must have at least one literal", self._cur())
        return EnumType(name=name, literals=tuple(literals))
    
    def _parse_class(self) -> Class:
        """Parse class definition."""
        is_abstract = self._accept_kw("KW_ABSTRACT")
        self._expect("KW_CLASS")
        name = self._expect("IDENT").text
        
        parent: Optional[ClassId] = None
        if self._accept_kw("KW_EXTENDS"):
            parent = ClassId(self._expect("IDENT").text)
        
        attributes: list[Attribute] = []
        self._expect_sym("{")
        while not self._at_sym("}"):
            attributes.append(self._parse_attribute())
        self._expect_sym("}")
        
        return Class(
            id=ClassId(name),
            name=name,
            is_abstract=is_abstract,
            parent=parent,
            attributes=tuple(attributes),
        )
    
    def _parse_attribute(self) -> Attribute:
        """Parse attribute definition."""
        name = self._expect("IDENT").text
        self._expect_sym(":")
        
        # Type
        type_token = self._cur()
        int_range: Optional[tuple[int, int]] = None
        string_vocab: tuple[str, ...] = ()
        if type_token.kind in ("KW_INT_TYPE", "KW_STRING_TYPE", "KW_BOOL_TYPE", "KW_REAL_TYPE"):
            self.pos += 1
            attr_type = type_token.text
            if attr_type == "Int" and self._at_sym("["):
                # Int[lo..hi]
                self._expect_sym("[")
                lo = int(self._expect("INT").text)
                self._expect_sym("..")
                hi = int(self._expect("INT").text)
                self._expect_sym("]")
                if lo > hi:
                    raise ParseError(f"Invalid Int range [{lo}..{hi}]", self._cur())
                int_range = (lo, hi)
            elif attr_type == "String" and self._at_sym("{"):
                # String{v1, v2, ...}
                self._expect_sym("{")
                vocab: list[str] = []
                while not self._at_sym("}"):
                    if self._at("STRING"):
                        lit = self._expect("STRING").text
                        vocab.append(lit.strip('"'))
                    elif self._at("IDENT"):
                        vocab.append(self._expect("IDENT").text)
                    else:
                        raise ParseError(
                            f"Expected string literal or identifier in String vocabulary, got {self._cur().text!r}",
                            self._cur(),
                        )
                    self._accept_sym(",")
                self._expect_sym("}")
                if not vocab:
                    raise ParseError("String vocabulary must be non-empty", self._cur())
                string_vocab = tuple(vocab)
        elif type_token.kind == "IDENT":
            self.pos += 1
            attr_type = type_token.text
        else:
            raise ParseError(f"Expected type, got {type_token.text!r}", type_token)
        
        # Optional default
        default = None
        if self._accept_sym(":="):
            default = self._cur().text
            self.pos += 1
        
        return Attribute(
            name=name,
            type=attr_type,
            default=default,
            int_range=int_range,
            string_vocab=string_vocab,
        )
    
    def _parse_association(self) -> Association:
        """Parse association definition."""
        is_containment = self._accept_kw("KW_CONTAINMENT")
        self._expect("KW_ASSOC")
        name = self._expect("IDENT").text
        self._expect_sym(":")
        
        # Source class and multiplicity
        source_class = ClassId(self._expect("IDENT").text)
        source_mult = self._parse_multiplicity()
        
        self._expect_sym("--")
        
        # Target class and multiplicity
        target_class = ClassId(self._expect("IDENT").text)
        target_mult = self._parse_multiplicity()
        
        return Association(
            id=AssocId(name),
            name=name,
            source_class=source_class,
            target_class=target_class,
            source_mult=source_mult,
            target_mult=target_mult,
            is_containment=is_containment,
        )
    
    def _parse_multiplicity(self) -> tuple[int, Optional[int]]:
        """Parse multiplicity [min..max] or [n]."""
        self._expect_sym("[")
        
        min_val = int(self._expect("INT").text)
        
        if self._accept_sym(".."):
            if self._at_sym("*"):
                self.pos += 1
                max_val = None
            else:
                max_val = int(self._expect("INT").text)
        else:
            max_val = min_val
        
        self._expect_sym("]")
        return (min_val, max_val)
    
    # -------------------------------------------------------------------------
    # Transformation parsing
    # -------------------------------------------------------------------------
    
    def _parse_transformation(self, metamodels: dict[str, Metamodel]) -> Transformation:
        """Parse transformation definition."""
        self._expect("KW_TRANSFORMATION")
        name = self._expect("IDENT").text
        self._expect_sym(":")
        
        source_mm_name = self._expect("IDENT").text
        self._expect_sym("->")
        target_mm_name = self._expect("IDENT").text
        
        if source_mm_name not in metamodels:
            raise ParseError(f"Unknown source metamodel: {source_mm_name}", self._cur())
        if target_mm_name not in metamodels:
            raise ParseError(f"Unknown target metamodel: {target_mm_name}", self._cur())
        
        source_mm = metamodels[source_mm_name]
        target_mm = metamodels[target_mm_name]
        
        self._expect_sym("{")
        
        layers: list[Layer] = []
        while not self._at_sym("}"):
            layers.append(self._parse_layer(source_mm, target_mm))
        
        self._expect_sym("}")
        
        return Transformation(
            name=name,
            source_metamodel=source_mm,
            target_metamodel=target_mm,
            layers=tuple(layers),
        )
    
    def _parse_layer(self, source_mm: Metamodel, target_mm: Metamodel) -> Layer:
        """Parse layer definition."""
        self._expect("KW_LAYER")
        name = self._expect("IDENT").text
        self._expect_sym("{")
        
        rules: list[Rule] = []
        while not self._at_sym("}"):
            rules.append(self._parse_rule(source_mm, target_mm))
        
        self._expect_sym("}")
        
        return Layer(id=LayerId(name), name=name, rules=tuple(rules))
    
    def _parse_rule(self, source_mm: Metamodel, target_mm: Metamodel) -> Rule:
        """Parse rule definition."""
        self._expect("KW_RULE")
        name = self._expect("IDENT").text
        self._expect_sym("{")
        
        match_elements: list[MatchElement] = []
        match_links: list[MatchLink] = []
        apply_elements: list[ApplyElement] = []
        apply_links: list[ApplyLink] = []
        backward_links: list[BackwardLink] = []
        guard: Optional[Expr] = None
        
        # Match block
        self._expect("KW_MATCH")
        self._expect_sym("{")
        while not self._at_sym("}"):
            elem_or_link = self._parse_match_item(source_mm)
            if isinstance(elem_or_link, MatchElement):
                match_elements.append(elem_or_link)
            else:
                match_links.append(elem_or_link)
        self._expect_sym("}")
        
        # Apply block
        self._expect("KW_APPLY")
        self._expect_sym("{")
        while not self._at_sym("}"):
            elem_or_link = self._parse_apply_item(target_mm)
            if isinstance(elem_or_link, ApplyElement):
                apply_elements.append(elem_or_link)
            else:
                apply_links.append(elem_or_link)
        self._expect_sym("}")
        
        # Optional backward block
        if self._accept_kw("KW_BACKWARD"):
            self._expect_sym("{")
            while not self._at_sym("}"):
                backward_links.append(self._parse_backward_link())
            self._expect_sym("}")
        
        # Optional guard block
        if self._accept_kw("KW_GUARD"):
            self._expect_sym("{")
            guard = self._parse_expr()
            self._expect_sym("}")
        
        self._expect_sym("}")
        
        return Rule(
            id=RuleId(name),
            name=name,
            match_elements=tuple(match_elements),
            match_links=tuple(match_links),
            apply_elements=tuple(apply_elements),
            apply_links=tuple(apply_links),
            backward_links=tuple(backward_links),
            guard=guard,
        )
    
    def _parse_match_item(self, mm: Metamodel) -> MatchElement | MatchLink:
        """Parse match element or match link."""
        # Check for link keywords first
        if self._at_kw("KW_DIRECT", "KW_INDIRECT"):
            return self._parse_match_link(mm)
        
        # Match element: any/exists name : Type [where condition]
        match_type = MatchType.ANY
        if self._accept_kw("KW_ANY"):
            match_type = MatchType.ANY
        elif self._accept_kw("KW_EXISTS"):
            match_type = MatchType.EXISTS
        
        name = self._expect("IDENT").text
        self._expect_sym(":")
        class_name = self._expect("IDENT").text
        
        # Optional where clause with typed expression
        where_clause: Optional[Expr] = None
        conditions: list[str] = []
        if self._accept_kw("KW_WHERE"):
            # Try to parse as typed expression
            try:
                where_clause = self._parse_expr()
            except ParseError:
                # Fall back to legacy string parsing
                conditions.append(self._parse_condition_expr())
        
        return MatchElement(
            id=ElementId(name),
            name=name,
            class_type=ClassId(class_name),
            match_type=match_type,
            attribute_conditions=tuple(conditions),
            where_clause=where_clause,
        )
    
    def _parse_match_link(self, mm: Metamodel) -> MatchLink:
        """
        Parse match link.
        
        Syntax:
          - Direct: direct name : assoc -- source.target
          - Indirect: indirect name : source -- target
        """
        kind = LinkKind.DIRECT
        if self._accept_kw("KW_DIRECT"):
            kind = LinkKind.DIRECT
        elif self._accept_kw("KW_INDIRECT"):
            kind = LinkKind.INDIRECT
        
        name = self._expect("IDENT").text
        self._expect_sym(":")
        
        if kind == LinkKind.INDIRECT:
            # Indirect: name : source -- target (no assoc type, path is implicit)
            source = self._expect("IDENT").text
            self._expect_sym("--")
            target = self._expect("IDENT").text
            assoc_name = "_indirect_"  # Placeholder for indirect path
        else:
            # Direct: name : assoc -- source.target
            assoc_name = self._expect("IDENT").text
            self._expect_sym("--")
            source = self._expect("IDENT").text
            self._expect_sym(".")
            target = self._expect("IDENT").text
        
        return MatchLink(
            id=ElementId(name),
            name=name,
            assoc_type=AssocId(assoc_name),
            source=ElementId(source),
            target=ElementId(target),
            kind=kind,
        )
    
    def _parse_apply_item(self, mm: Metamodel) -> ApplyElement | ApplyLink:
        """Parse apply element or apply link."""
        name = self._expect("IDENT").text
        self._expect_sym(":")
        
        # Check if it's a link (assoc_name -- source.target) or element (Type)
        type_or_assoc = self._expect("IDENT").text
        
        if self._at_sym("--"):
            # It's a link
            self._expect_sym("--")
            source = self._expect("IDENT").text
            self._expect_sym(".")
            target = self._expect("IDENT").text
            return ApplyLink(
                id=ElementId(name),
                name=name,
                assoc_type=AssocId(type_or_assoc),
                source=ElementId(source),
                target=ElementId(target),
            )
        else:
            # It's an element, optionally with attribute bindings
            assignments: list[str] = []
            bindings: list[AttributeBinding] = []
            
            # Check for attribute bindings block: { attr = expr, ... }
            if self._at_sym("{"):
                self._expect_sym("{")
                while not self._at_sym("}"):
                    attr_name = self._expect("IDENT").text
                    self._expect_sym("=")
                    value_expr = self._parse_expr()
                    bindings.append(AttributeBinding(
                        target=AttrRef(element=name, attribute=attr_name),
                        value=value_expr,
                    ))
                    # Optional comma separator
                    self._accept_sym(",")
                self._expect_sym("}")
            
            return ApplyElement(
                id=ElementId(name),
                name=name,
                class_type=ClassId(type_or_assoc),
                attribute_assignments=tuple(assignments),
                attribute_bindings=tuple(bindings),
            )
    
    def _parse_backward_link(self) -> BackwardLink:
        """Parse backward link: apply.elem <--trace-- match_elem"""
        # Format: apply.elem <--trace-- match_elem
        # Or: elem <--trace-- elem (simplified)
        
        # Apply element (with optional apply. prefix)
        if self._at("IDENT") and self._peek(1).text == ".":
            self._expect("IDENT")  # "apply"
            self._expect_sym(".")
        apply_elem = self._expect("IDENT").text
        
        self._expect_sym("<--trace--")
        
        match_elem = self._expect("IDENT").text
        
        return BackwardLink(
            apply_element=ElementId(apply_elem),
            match_element=ElementId(match_elem),
        )
    
    def _parse_condition_expr(self) -> str:
        """Parse attribute condition expression (simplified: just collect tokens)."""
        parts: list[str] = []
        depth = 0
        while True:
            t = self._cur()
            if t.kind == "EOF":
                break
            if t.text == "{":
                break
            if t.text == "}" and depth == 0:
                break
            if t.text == "(":
                depth += 1
            if t.text == ")":
                depth -= 1
                if depth < 0:
                    break
            parts.append(t.text)
            self.pos += 1
        return " ".join(parts)
    
    # -------------------------------------------------------------------------
    # Expression parsing (for algebraic data types)
    # -------------------------------------------------------------------------
    
    def _parse_expr(self) -> Expr:
        """Parse expression (top-level entry point)."""
        return self._parse_or_expr()
    
    def _parse_or_expr(self) -> Expr:
        """Parse OR expression: <AndExpr> ('||' <AndExpr>)*"""
        left = self._parse_and_expr()
        while self._at_sym("||"):
            self._expect_sym("||")
            right = self._parse_and_expr()
            left = BinOp(op="||", left=left, right=right)
        return left
    
    def _parse_and_expr(self) -> Expr:
        """Parse AND expression: <CompExpr> ('&&' <CompExpr>)*"""
        left = self._parse_comp_expr()
        while self._at_sym("&&"):
            self._expect_sym("&&")
            right = self._parse_comp_expr()
            left = BinOp(op="&&", left=left, right=right)
        return left
    
    def _parse_comp_expr(self) -> Expr:
        """Parse comparison expression: <ArithExpr> (comp_op <ArithExpr>)?"""
        left = self._parse_arith_expr()
        if self._at_sym("==") or self._at_sym("!=") or self._at_sym("<") or \
           self._at_sym("<=") or self._at_sym(">") or self._at_sym(">="):
            op = self._cur().text
            self.pos += 1
            right = self._parse_arith_expr()
            return BinOp(op=op, left=left, right=right)
        return left
    
    def _parse_arith_expr(self) -> Expr:
        """Parse arithmetic expression: <Term> (('+' | '-') <Term>)*"""
        left = self._parse_term()
        while self._at_sym("+") or self._at_sym("-"):
            op = self._cur().text
            self.pos += 1
            right = self._parse_term()
            left = BinOp(op=op, left=left, right=right)
        return left
    
    def _parse_term(self) -> Expr:
        """Parse term: <Factor> (('*' | '/' | '%') <Factor>)*"""
        left = self._parse_factor()
        while self._at_sym("*") or self._at_sym("/") or self._at_sym("%"):
            op = self._cur().text
            self.pos += 1
            right = self._parse_factor()
            left = BinOp(op=op, left=left, right=right)
        return left
    
    def _parse_factor(self) -> Expr:
        """Parse factor: <Primary> | '!' <Factor> | '-' <Factor>"""
        if self._at_sym("!"):
            self._expect_sym("!")
            operand = self._parse_factor()
            return UnaryOp(op="!", operand=operand)
        if self._at_sym("-"):
            self._expect_sym("-")
            operand = self._parse_factor()
            return UnaryOp(op="-", operand=operand)
        return self._parse_primary()
    
    def _parse_primary(self) -> Expr:
        """
        Parse primary expression:
          - INT literal
          - STRING literal
          - true/false
          - List literal: '[' expr, ... ']'
          - Pair literal: '(' expr ',' expr ')'
          - Function call: name '(' args ')'
          - Attribute ref: ident '.' ident
          - Variable ref: ident
          - Grouped expr: '(' expr ')'
        """
        t = self._cur()
        
        # Integer literal
        if t.kind == "INT":
            self.pos += 1
            return IntLit(value=int(t.text))
        
        # String literal
        if t.kind == "STRING":
            self.pos += 1
            return StringLit(value=t.text)
        
        # Boolean literals
        if t.kind == "KW_TRUE":
            self.pos += 1
            return BoolLit(value=True)
        if t.kind == "KW_FALSE":
            self.pos += 1
            return BoolLit(value=False)
        
        # List literal: [expr, expr, ...]
        if self._at_sym("["):
            self._expect_sym("[")
            elements: list[Expr] = []
            if not self._at_sym("]"):
                elements.append(self._parse_expr())
                while self._accept_sym(","):
                    elements.append(self._parse_expr())
            self._expect_sym("]")
            return ListLit(elements=tuple(elements))
        
        # Parenthesized expression or pair literal
        if self._at_sym("("):
            self._expect_sym("(")
            first = self._parse_expr()
            if self._at_sym(","):
                # Pair literal: (expr, expr)
                self._expect_sym(",")
                second = self._parse_expr()
                self._expect_sym(")")
                return PairLit(fst=first, snd=second)
            else:
                # Grouped expression
                self._expect_sym(")")
                return first
        
        # Builtin function call: head, tail, append, concat, length, fst, snd, isEmpty
        if t.kind in ("KW_HEAD", "KW_TAIL", "KW_APPEND", "KW_CONCAT", 
                      "KW_LENGTH", "KW_FST", "KW_SND", "KW_ISEMPTY"):
            func_name = t.text
            self.pos += 1
            self._expect_sym("(")
            args: list[Expr] = []
            if not self._at_sym(")"):
                args.append(self._parse_expr())
                while self._accept_sym(","):
                    args.append(self._parse_expr())
            self._expect_sym(")")
            return FuncCall(name=func_name, args=tuple(args))
        
        # Identifier: variable, attribute reference, or function call
        if t.kind == "IDENT":
            name = t.text
            self.pos += 1
            
            # Check for function call: name(args)
            if self._at_sym("("):
                self._expect_sym("(")
                args = []
                if not self._at_sym(")"):
                    args.append(self._parse_expr())
                    while self._accept_sym(","):
                        args.append(self._parse_expr())
                self._expect_sym(")")
                return FuncCall(name=name, args=tuple(args))
            
            # Check for attribute reference: elem.attr
            if self._at_sym("."):
                self._expect_sym(".")
                attr = self._expect("IDENT").text
                return AttrRef(element=name, attribute=attr)
            
            # Simple variable reference
            return VarRef(name=name)
        
        raise ParseError(f"Expected expression, got {t.text!r}", t)
    
    # -------------------------------------------------------------------------
    # Property parsing
    # -------------------------------------------------------------------------
    
    def _parse_property(self) -> Property:
        """Parse property (contract) definition."""
        self._expect("KW_PROPERTY")
        name = self._expect("IDENT").text
        # Optional human-readable description: property Name "..." { ... }
        if self._at("STRING"):
            self.pos += 1
        self._expect_sym("{")
        
        precondition: Optional[PreCondition] = None
        postcondition: Optional[PostCondition] = None
        
        # Optional precondition
        if self._accept_kw("KW_PRECONDITION"):
            self._expect_sym("{")
            pre_elems, pre_links = self._parse_pattern_content()
            self._expect_sym("}")
            precondition = PreCondition(elements=tuple(pre_elems), links=tuple(pre_links))
        
        # Required postcondition
        self._expect("KW_POSTCONDITION")
        self._expect_sym("{")
        post_content = self._parse_postcondition_content()
        self._expect_sym("}")
        
        self._expect_sym("}")
        
        return Property(
            id=name,
            name=name,
            precondition=precondition,
            postcondition=post_content,
        )
    
    def _parse_pattern_content(self) -> tuple[list[MatchElement], list[MatchLink]]:
        """Parse pattern content (elements and links)."""
        elements: list[MatchElement] = []
        links: list[MatchLink] = []
        
        while not self._at_sym("}"):
            if self._at_kw("KW_DIRECT", "KW_INDIRECT"):
                links.append(self._parse_match_link_simple())
            elif self._at_kw("KW_ANY", "KW_EXISTS") or self._at("IDENT"):
                elements.append(self._parse_match_element_simple())
            else:
                raise ParseError(f"Unexpected in pattern: {self._cur().text!r}", self._cur())
        
        return elements, links
    
    def _parse_match_element_simple(self) -> MatchElement:
        """Parse simplified match element with optional where clause."""
        match_type = MatchType.ANY
        if self._accept_kw("KW_ANY"):
            match_type = MatchType.ANY
        elif self._accept_kw("KW_EXISTS"):
            match_type = MatchType.EXISTS
        
        name = self._expect("IDENT").text
        self._expect_sym(":")
        class_name = self._expect("IDENT").text
        
        # Optional where clause
        where_clause: Optional[Expr] = None
        if self._accept_kw("KW_WHERE"):
            where_clause = self._parse_expr()
        
        return MatchElement(
            id=ElementId(name),
            name=name,
            class_type=ClassId(class_name),
            match_type=match_type,
            where_clause=where_clause,
        )
    
    def _parse_match_link_simple(self) -> MatchLink:
        """
        Parse simplified match link.
        
        Syntax:
          - Direct: direct name : assoc -- source.target
          - Indirect: indirect name : source -- target
        """
        kind = LinkKind.DIRECT
        if self._accept_kw("KW_DIRECT"):
            kind = LinkKind.DIRECT
        elif self._accept_kw("KW_INDIRECT"):
            kind = LinkKind.INDIRECT
        
        name = self._expect("IDENT").text
        self._expect_sym(":")
        
        if kind == LinkKind.INDIRECT:
            # Indirect: name : source -- target (no assoc type, path is implicit)
            source = self._expect("IDENT").text
            self._expect_sym("--")
            target = self._expect("IDENT").text
            assoc_name = "_indirect_"  # Placeholder for indirect path
        else:
            # Direct: name : assoc -- source.target
            assoc_name = self._expect("IDENT").text
            self._expect_sym("--")
            source = self._expect("IDENT").text
            self._expect_sym(".")
            target = self._expect("IDENT").text
        
        return MatchLink(
            id=ElementId(name),
            name=name,
            assoc_type=AssocId(assoc_name),
            source=ElementId(source),
            target=ElementId(target),
            kind=kind,
        )
    
    def _parse_postcondition_content(self) -> PostCondition:
        """Parse postcondition content with traceability links."""
        elements: list[ApplyElement] = []
        links: list[ApplyLink] = []
        trace_links: list[tuple[ElementId, ElementId]] = []
        
        while not self._at_sym("}"):
            # Check for trace link: elem <--trace-- elem
            if self._at("IDENT"):
                name = self._cur().text
                if self._peek(1).text == "<--trace--":
                    self.pos += 1  # consume name
                    self._expect_sym("<--trace--")
                    match_name = self._expect("IDENT").text
                    trace_links.append((ElementId(name), ElementId(match_name)))
                    continue
                
                # Otherwise it's an element or link
                self.pos += 1  # consume name
                self._expect_sym(":")
                type_or_assoc = self._expect("IDENT").text
                
                if self._at_sym("--"):
                    # It's a link
                    self._expect_sym("--")
                    source = self._expect("IDENT").text
                    self._expect_sym(".")
                    target = self._expect("IDENT").text
                    links.append(ApplyLink(
                        id=ElementId(name),
                        name=name,
                        assoc_type=AssocId(type_or_assoc),
                        source=ElementId(source),
                        target=ElementId(target),
                    ))
                else:
                    # It's an element - check for bind clause
                    elements.append(ApplyElement(
                        id=ElementId(name),
                        name=name,
                        class_type=ClassId(type_or_assoc),
                    ))
            else:
                raise ParseError(f"Unexpected in postcondition: {self._cur().text!r}", self._cur())
        
        return PostCondition(
            elements=tuple(elements),
            links=tuple(links),
            trace_links=tuple(trace_links),
        )
    
    def _parse_composite_property(self) -> CompositeProperty:
        """Parse composite property."""
        self._expect("KW_COMPOSITE")
        name = self._expect("IDENT").text
        self._expect_sym("{")
        
        atomics: list[Property] = []
        formula = ""
        bindings: list[tuple[str, str]] = []
        
        while not self._at_sym("}"):
            if self._accept_kw("KW_ATOMIC"):
                atomic_name = self._expect("IDENT").text
                self._expect_sym("=")
                prop = self._parse_property()
                prop = Property(
                    id=atomic_name,
                    name=atomic_name,
                    precondition=prop.precondition,
                    postcondition=prop.postcondition,
                )
                atomics.append(prop)
            elif self._accept_kw("KW_FORMULA"):
                self._expect_sym(":")
                formula = self._parse_formula_expr()
            else:
                raise ParseError(f"Unexpected in composite: {self._cur().text!r}", self._cur())
        
        self._expect_sym("}")
        
        return CompositeProperty(
            id=name,
            name=name,
            atomics=tuple(atomics),
            formula=formula,
            free_var_bindings=tuple(bindings),
        )
    
    def _parse_formula_expr(self) -> str:
        """Parse formula expression (collect tokens until end)."""
        parts: list[str] = []
        while not self._at_sym("}"):
            parts.append(self._cur().text)
            self.pos += 1
        return " ".join(parts)


def parse_dsltrans(src: str) -> ParsedSpec:
    """Parse DSLTrans specification from source string."""
    parser = Parser(src)
    return parser.parse()


def parse_dsltrans_file(path: str | Path) -> ParsedSpec:
    """Parse DSLTrans specification from file."""
    src = Path(path).read_text(encoding="utf-8")
    return parse_dsltrans(src)
