from __future__ import annotations

from dataclasses import dataclass

from .model import (
    AttrRef,
    BinOp,
    BoolLit,
    Expr,
    FuncCall,
    IntLit,
    ListLit,
    PairLit,
    StringLit,
    UnaryOp,
    VarRef,
)


@dataclass
class RuntimeExprEvaluator:
    """Evaluates DSLTrans expression AST over concrete environments."""

    env: dict[str, object]

    def eval(self, expr: Expr) -> object:
        if isinstance(expr, IntLit):
            return expr.value
        if isinstance(expr, BoolLit):
            return expr.value
        if isinstance(expr, StringLit):
            # Parser keeps quotes in string literals.
            return expr.value.strip('"')
        if isinstance(expr, ListLit):
            return [self.eval(e) for e in expr.elements]
        if isinstance(expr, PairLit):
            return (self.eval(expr.fst), self.eval(expr.snd))
        if isinstance(expr, VarRef):
            if expr.name not in self.env:
                raise KeyError(f"Unknown variable {expr.name!r} in expression")
            return self.env[expr.name]
        if isinstance(expr, AttrRef):
            key = f"{expr.element}.{expr.attribute}"
            if key not in self.env:
                raise KeyError(f"Unknown attribute reference {key!r} in expression")
            return self.env[key]
        if isinstance(expr, UnaryOp):
            return self._eval_unary(expr)
        if isinstance(expr, BinOp):
            return self._eval_binary(expr)
        if isinstance(expr, FuncCall):
            return self._eval_func(expr)
        raise TypeError(f"Unsupported expression node: {type(expr).__name__}")

    def _eval_unary(self, expr: UnaryOp) -> object:
        val = self.eval(expr.operand)
        if expr.op == "!":
            return not bool(val)
        if expr.op == "-":
            return -int(val)
        raise ValueError(f"Unsupported unary operator: {expr.op}")

    def _eval_binary(self, expr: BinOp) -> object:
        left = self.eval(expr.left)
        right = self.eval(expr.right)
        op = expr.op
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return left // right if isinstance(left, int) and isinstance(right, int) else left / right
        if op == "%":
            return left % right
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if left is None or right is None:
            # In concrete models, optional/unset attributes are represented as None.
            # Guard-style comparisons against missing values should simply not match.
            return False
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "&&":
            return bool(left) and bool(right)
        if op == "||":
            return bool(left) or bool(right)
        raise ValueError(f"Unsupported binary operator: {op}")

    def _eval_func(self, expr: FuncCall) -> object:
        args = [self.eval(a) for a in expr.args]
        name = expr.name
        if name == "head":
            return args[0][0]
        if name == "tail":
            return args[0][1:]
        if name == "append":
            return list(args[0]) + [args[1]]
        if name == "concat":
            return list(args[0]) + list(args[1])
        if name == "length":
            return len(args[0])
        if name == "fst":
            return args[0][0]
        if name == "snd":
            return args[0][1]
        if name == "isEmpty":
            return len(args[0]) == 0
        raise ValueError(f"Unsupported function: {name}")
