"""
DSLTrans Lexer

Tokenizes DSLTrans textual specifications following the grammar in dsltrans.tex.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterator, Literal


TokenKind = Literal[
    # Identifiers and literals
    "IDENT",
    "INT",
    "STRING",
    # Metamodel keywords
    "KW_METAMODEL",
    "KW_CLASS",
    "KW_ABSTRACT",
    "KW_EXTENDS",
    "KW_ASSOC",
    "KW_CONTAINMENT",
    "KW_ENUM",
    # Type keywords
    "KW_INT_TYPE",
    "KW_STRING_TYPE",
    "KW_BOOL_TYPE",
    "KW_REAL_TYPE",
    "KW_LIST_TYPE",
    "KW_PAIR_TYPE",
    # Rule keywords
    "KW_RULE",
    "KW_MATCH",
    "KW_APPLY",
    "KW_BACKWARD",
    "KW_ANY",
    "KW_EXISTS",
    "KW_DIRECT",
    "KW_INDIRECT",
    "KW_WHERE",
    "KW_GUARD",
    # Transformation keywords
    "KW_TRANSFORMATION",
    "KW_LAYER",
    # Property keywords
    "KW_PROPERTY",
    "KW_COMPOSITE",
    "KW_ATOMIC",
    "KW_PRECONDITION",
    "KW_POSTCONDITION",
    "KW_FORMULA",
    "KW_BIND",
    "KW_AS",
    # Logical operators
    "KW_AND",
    "KW_OR",
    "KW_NOT",
    "KW_IMPLIES",
    # Boolean literals
    "KW_TRUE",
    "KW_FALSE",
    # Builtin functions
    "KW_HEAD",
    "KW_TAIL",
    "KW_APPEND",
    "KW_CONCAT",
    "KW_LENGTH",
    "KW_FST",
    "KW_SND",
    "KW_ISEMPTY",
    # Symbols
    "SYM",
    # End of file
    "EOF",
]


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    pos: int
    line: int = 0
    col: int = 0


_WS = re.compile(r"\s+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INT = re.compile(r"[0-9]+")
_STRING = re.compile(r'"[^"]*"')

# Symbols sorted by length (longest first)
_SYMS = [
    "<--trace--",  # Backward link / trace requirement
    ":=",          # Assignment
    "->",          # Transformation arrow
    "..",          # Range
    "--",          # Association link
    "&&",          # Logical AND
    "||",          # Logical OR
    "==",
    "!=",
    "<=",
    ">=",
    "{",
    "}",
    "(",
    ")",
    "[",
    "]",
    ";",
    ":",
    "=",
    "+",
    "-",
    "*",
    "/",
    "%",            # Modulo
    "<",
    ">",
    ".",
    ",",
    "!",            # Logical NOT
]

_SYMS_RE = re.compile("|".join(re.escape(s) for s in sorted(_SYMS, key=len, reverse=True)))

_KEYWORDS = {
    # Metamodel
    "metamodel": "KW_METAMODEL",
    "class": "KW_CLASS",
    "abstract": "KW_ABSTRACT",
    "extends": "KW_EXTENDS",
    "assoc": "KW_ASSOC",
    "containment": "KW_CONTAINMENT",
    "enum": "KW_ENUM",
    # Types
    "Int": "KW_INT_TYPE",
    "String": "KW_STRING_TYPE",
    "Bool": "KW_BOOL_TYPE",
    "Real": "KW_REAL_TYPE",
    "List": "KW_LIST_TYPE",
    "Pair": "KW_PAIR_TYPE",
    # Rule
    "rule": "KW_RULE",
    "match": "KW_MATCH",
    "apply": "KW_APPLY",
    "backward": "KW_BACKWARD",
    "any": "KW_ANY",
    "exists": "KW_EXISTS",
    "direct": "KW_DIRECT",
    "indirect": "KW_INDIRECT",
    "where": "KW_WHERE",
    "guard": "KW_GUARD",
    # Transformation
    "transformation": "KW_TRANSFORMATION",
    "layer": "KW_LAYER",
    # Property
    "property": "KW_PROPERTY",
    "composite": "KW_COMPOSITE",
    "atomic": "KW_ATOMIC",
    "precondition": "KW_PRECONDITION",
    "postcondition": "KW_POSTCONDITION",
    "formula": "KW_FORMULA",
    "bind": "KW_BIND",
    "as": "KW_AS",
    # Logical
    "and": "KW_AND",
    "or": "KW_OR",
    "not": "KW_NOT",
    "implies": "KW_IMPLIES",
    # Boolean literals
    "true": "KW_TRUE",
    "false": "KW_FALSE",
    # Builtin functions
    "head": "KW_HEAD",
    "tail": "KW_TAIL",
    "append": "KW_APPEND",
    "concat": "KW_CONCAT",
    "length": "KW_LENGTH",
    "fst": "KW_FST",
    "snd": "KW_SND",
    "isEmpty": "KW_ISEMPTY",
}


class LexError(ValueError):
    """Lexer error with position information."""
    
    def __init__(self, msg: str, pos: int, line: int = 0, col: int = 0):
        super().__init__(f"Lex error at position {pos} (line {line}, col {col}): {msg}")
        self.pos = pos
        self.line = line
        self.col = col


def _compute_line_col(src: str, pos: int) -> tuple[int, int]:
    """Compute line and column number for a position."""
    line = src[:pos].count("\n") + 1
    last_nl = src.rfind("\n", 0, pos)
    col = pos - last_nl if last_nl >= 0 else pos + 1
    return line, col


def lex(src: str) -> Iterator[Token]:
    """
    Tokenize DSLTrans source code.
    
    Handles:
      - Line comments: // ...
      - Block comments: /* ... */
      - All DSLTrans keywords and symbols
    """
    i = 0
    n = len(src)
    
    while i < n:
        line, col = _compute_line_col(src, i)
        
        # Line comment: // ... (skip to end of line)
        # Note: We use // instead of -- because -- is the association separator
        if src.startswith("//", i):
            j = src.find("\n", i + 2)
            if j == -1:
                break
            i = j + 1
            continue
        
        # Block comment: /* ... */ (skip entire block)
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j == -1:
                raise LexError("Unterminated block comment", i, line, col)
            i = j + 2
            continue
        
        # Whitespace
        m = _WS.match(src, i)
        if m:
            i = m.end()
            continue
        
        # String literals
        m = _STRING.match(src, i)
        if m:
            text = m.group(0)
            yield Token("STRING", text[1:-1], i, line, col)  # Strip quotes
            i = m.end()
            continue
        
        # Symbols (check before identifiers)
        m = _SYMS_RE.match(src, i)
        if m:
            text = m.group(0)
            yield Token("SYM", text, i, line, col)
            i = m.end()
            continue
        
        # Integer literals
        m = _INT.match(src, i)
        if m:
            text = m.group(0)
            yield Token("INT", text, i, line, col)
            i = m.end()
            continue
        
        # Identifiers and keywords
        m = _IDENT.match(src, i)
        if m:
            text = m.group(0)
            kind = _KEYWORDS.get(text, "IDENT")
            yield Token(kind, text, i, line, col)
            i = m.end()
            continue
        
        raise LexError(f"Unexpected character: {src[i]!r}", i, line, col)
    
    line, col = _compute_line_col(src, n)
    yield Token("EOF", "", n, line, col)


def tokens(src: str) -> list[Token]:
    """Convenience function to get all tokens as a list."""
    return list(lex(src))
