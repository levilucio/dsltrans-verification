from __future__ import annotations

from typing import Iterable

from .model import (
    ApplyElement,
    ApplyLink,
    Association,
    AttrRef,
    BinOp,
    BoolLit,
    Class,
    CompositeProperty,
    Expr,
    FuncCall,
    IntLit,
    LinkKind,
    ListLit,
    MatchElement,
    MatchLink,
    MatchType,
    PairLit,
    PostCondition,
    PreCondition,
    Property,
    StringLit,
    Transformation,
    UnaryOp,
    VarRef,
)
from .parser import ParsedSpec


def _quote_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_expr(expr: Expr) -> str:
    if isinstance(expr, IntLit):
        return str(expr.value)
    if isinstance(expr, BoolLit):
        return "true" if expr.value else "false"
    if isinstance(expr, StringLit):
        raw = expr.value
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        return _quote_string(raw)
    if isinstance(expr, ListLit):
        return "[" + ", ".join(_render_expr(e) for e in expr.elements) + "]"
    if isinstance(expr, PairLit):
        return f"({_render_expr(expr.fst)}, {_render_expr(expr.snd)})"
    if isinstance(expr, VarRef):
        return expr.name
    if isinstance(expr, AttrRef):
        return f"{expr.element}.{expr.attribute}"
    if isinstance(expr, UnaryOp):
        return f"{expr.op}{_render_expr(expr.operand)}"
    if isinstance(expr, BinOp):
        return f"{_render_expr(expr.left)} {expr.op} {_render_expr(expr.right)}"
    if isinstance(expr, FuncCall):
        return f"{expr.name}(" + ", ".join(_render_expr(a) for a in expr.args) + ")"
    raise TypeError(f"Unsupported expression node: {type(expr).__name__}")


def _render_attribute(attr) -> str:
    rendered_type = attr.type
    if (attr.type or "").strip().lower() in ("int", "integer") and attr.int_range is not None:
        lo, hi = attr.int_range
        rendered_type = f"Int[{lo}..{hi}]"
    elif (attr.type or "").strip().lower() == "string" and attr.string_vocab:
        rendered_type = "String{" + ", ".join(_quote_string(v) for v in attr.string_vocab) + "}"
    line = f"{attr.name}: {rendered_type}"
    if attr.default is not None:
        line += f" := {attr.default}"
    return line


def _render_class(cls: Class) -> list[str]:
    prefix = "abstract class" if cls.is_abstract else "class"
    header = f"{prefix} {cls.name}"
    if cls.parent is not None:
        header += f" extends {cls.parent}"
    if not cls.attributes:
        return [f"{header} {{ }}"]
    lines = [f"{header} {{"]
    for attr in cls.attributes:
        lines.append(f"    {_render_attribute(attr)}")
    lines.append("}")
    return lines


def _render_multiplicity(mult: tuple[int, int | None]) -> str:
    lo, hi = mult
    if hi is None:
        return f"[{lo}..*]"
    if lo == hi:
        return f"[{lo}]"
    return f"[{lo}..{hi}]"


def _render_association(assoc: Association) -> str:
    prefix = "containment assoc" if assoc.is_containment else "assoc"
    return (
        f"{prefix} {assoc.name}: {assoc.source_class}{_render_multiplicity(assoc.source_mult)} "
        f"-- {assoc.target_class}{_render_multiplicity(assoc.target_mult)}"
    )


def _render_match_element(elem: MatchElement) -> str:
    prefix = "exists" if elem.match_type == MatchType.EXISTS else "any"
    line = f"{prefix} {elem.name} : {elem.class_type}"
    if elem.where_clause is not None:
        line += f" where {_render_expr(elem.where_clause)}"
    return line


def _render_match_link(link: MatchLink) -> str:
    if link.kind == LinkKind.INDIRECT:
        return f"indirect {link.name} : {link.source} -- {link.target}"
    return f"direct {link.name} : {link.assoc_type} -- {link.source}.{link.target}"


def _render_apply_element(elem: ApplyElement) -> str:
    line = f"{elem.name} : {elem.class_type}"
    if elem.attribute_bindings:
        rendered = ", ".join(
            f"{binding.target.attribute} = {_render_expr(binding.value)}"
            for binding in elem.attribute_bindings
        )
        line += f" {{ {rendered} }}"
    return line


def _render_apply_link(link: ApplyLink) -> str:
    return f"{link.name} : {link.assoc_type} -- {link.source}.{link.target}"


def _render_backward_link(link) -> str:
    return f"{link.apply_element} <--trace-- {link.match_element}"


def _indent(lines: Iterable[str], spaces: int = 4) -> list[str]:
    prefix = " " * spaces
    return [prefix + line if line else "" for line in lines]


def _render_precondition(pre: PreCondition) -> list[str]:
    lines = ["precondition {"]
    for elem in pre.elements:
        lines.append(f"    {_render_match_element(elem)}")
    for link in pre.links:
        lines.append(f"    {_render_match_link(link)}")
    if pre.constraint is not None:
        lines.append(f"    where {_render_expr(pre.constraint)}")
    lines.append("}")
    return lines


def _render_postcondition(post: PostCondition) -> list[str]:
    lines = ["postcondition {"]
    for elem in post.elements:
        lines.append(f"    {_render_apply_element(elem)}")
    for link in post.links:
        lines.append(f"    {_render_apply_link(link)}")
    for post_elem, pre_elem in post.trace_links:
        lines.append(f"    {post_elem} <--trace-- {pre_elem}")
    lines.append("}")
    return lines


def render_spec(spec) -> str:
    lines: list[str] = []

    for mm in spec.metamodels:
        lines.append(f"metamodel {mm.name} {{")
        for cls in mm.classes:
            lines.extend(_indent(_render_class(cls)))
        for enum in mm.enums:
            lines.append(f"    enum {enum.name} {{ {', '.join(enum.literals)} }}")
        for assoc in mm.associations:
            lines.append(f"    {_render_association(assoc)}")
        lines.append("}")
        lines.append("")

    for trans in spec.transformations:
        lines.append(
            f"transformation {trans.name} : {trans.source_metamodel.name} -> {trans.target_metamodel.name} {{"
        )
        lines.append("")
        for layer in trans.layers:
            lines.append(f"    layer {layer.name} {{")
            for rule in layer.rules:
                lines.append(f"        rule {rule.name} {{")
                lines.append("            match {")
                for elem in rule.match_elements:
                    lines.append(f"                {_render_match_element(elem)}")
                for link in rule.match_links:
                    lines.append(f"                {_render_match_link(link)}")
                lines.append("            }")
                lines.append("            apply {")
                for elem in rule.apply_elements:
                    lines.append(f"                {_render_apply_element(elem)}")
                for link in rule.apply_links:
                    lines.append(f"                {_render_apply_link(link)}")
                lines.append("            }")
                if rule.backward_links:
                    lines.append("            backward {")
                    for link in rule.backward_links:
                        lines.append(f"                {_render_backward_link(link)}")
                    lines.append("            }")
                if rule.guard is not None:
                    lines.append("            guard {")
                    lines.append(f"                {_render_expr(rule.guard)}")
                    lines.append("            }")
                lines.append("        }")
            lines.append("    }")
            lines.append("")
        lines.append("}")
        lines.append("")

    for prop in spec.properties:
        if isinstance(prop, Property):
            lines.append(f"property {prop.name} {{")
            if prop.precondition is not None:
                lines.extend(_indent(_render_precondition(prop.precondition)))
            lines.extend(_indent(_render_postcondition(prop.postcondition)))
            lines.append("}")
            lines.append("")
        elif isinstance(prop, CompositeProperty):
            lines.append(f"composite {prop.name} {{")
            for atomic in prop.atomics:
                lines.append(f"    atomic {atomic.id} = property {atomic.name} {{")
                if atomic.precondition is not None:
                    lines.extend(_indent(_indent(_render_precondition(atomic.precondition))))
                lines.extend(_indent(_indent(_render_postcondition(atomic.postcondition))))
                lines.append("    }")
            lines.append(f"    formula: {prop.formula}")
            lines.append("}")
            lines.append("")
        else:
            raise TypeError(f"Unsupported property node: {type(prop).__name__}")

    return "\n".join(lines).rstrip() + "\n"
