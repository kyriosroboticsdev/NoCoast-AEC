"""A small, safe expression language for parametric geometry ("w - 0.1", "max(0.3, h / 2)",
"r * cos(i * 2 * pi / n)", "0.05 if w > 1 else 0").

Numbers, names, + - * / // % **, unary minus, comparisons, `and` / `or` / `not`, `a if c else b`,
and the functions in FUNCS. Anything else (attribute access, other calls, comprehensions, strings)
is rejected when a definition is loaded, so an asset — even one a model wrote — can never run code.
Comparisons and boolean operators evaluate to 1.0 / 0.0.
"""

from __future__ import annotations

import ast
import math
import operator
from functools import lru_cache

FUNCS = {
    "min": min, "max": max, "abs": abs, "sqrt": math.sqrt, "pow": math.pow, "floor": math.floor, "ceil": math.ceil,
    "round": round, "sin": lambda d: math.sin(math.radians(d)), "cos": lambda d: math.cos(math.radians(d)),
    "tan": lambda d: math.tan(math.radians(d)), "asin": lambda v: math.degrees(math.asin(v)),
    "acos": lambda v: math.degrees(math.acos(v)), "atan": lambda v: math.degrees(math.atan(v)),
    "atan2": lambda y, x: math.degrees(math.atan2(y, x)), "hypot": math.hypot,
    "clamp": lambda v, lo, hi: min(max(v, lo), hi),
}
CONSTANTS = {"pi": math.pi}
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
           ast.Eq: operator.eq, ast.NotEq: operator.ne}
MAX_POWER = 64


class ExprError(ValueError):
    pass


@lru_cache(maxsize=8192)
def _parse(text: str) -> ast.AST:
    try:
        tree = ast.parse(text, mode="eval").body
    except SyntaxError as exc:
        raise ExprError(f"bad expression {text!r}: {exc.msg}") from exc
    _validate(tree, text)
    return tree


def _validate(node: ast.AST, text: str) -> None:
    def bad(what: str):
        raise ExprError(f"{text!r}: {what} is not allowed")

    match node:
        case ast.Constant(value=v):
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                bad("a non-number constant")
        case ast.Name():
            pass
        case ast.BinOp(op=op, left=left, right=right):
            if type(op) not in BINOPS:
                bad(type(op).__name__)
            _validate(left, text)
            _validate(right, text)
        case ast.UnaryOp(op=op, operand=operand):
            if not isinstance(op, (ast.USub, ast.UAdd, ast.Not)):
                bad(type(op).__name__)
            _validate(operand, text)
        case ast.Compare(left=left, ops=ops, comparators=rest):
            if any(type(o) not in COMPARE for o in ops):
                bad("that comparison")
            for n in (left, *rest):
                _validate(n, text)
        case ast.BoolOp(values=values):
            for n in values:
                _validate(n, text)
        case ast.IfExp(test=test, body=body, orelse=orelse):
            for n in (test, body, orelse):
                _validate(n, text)
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]) if name in FUNCS:
            for n in args:
                _validate(n, text)
        case ast.Call():
            raise ExprError(f"{text!r}: only {', '.join(sorted(FUNCS))} may be called")
        case _:
            bad(type(node).__name__)


def names_in(text: str) -> set[str]:
    """Free names an expression reads (functions and constants excluded)."""
    return {n.id for n in ast.walk(_parse(text)) if isinstance(n, ast.Name) and n.id not in FUNCS and n.id not in CONSTANTS}


def evaluate(text: str, values: dict[str, float]) -> float:
    def run(node: ast.AST) -> float:
        match node:
            case ast.Constant(value=v):
                return float(v)
            case ast.Name(id=name):
                if name in values:
                    return float(values[name])
                if name in CONSTANTS:
                    return CONSTANTS[name]
                raise ExprError(f"{text!r}: unknown name '{name}'")
            case ast.BinOp(op=op, left=left, right=right):
                a, b = run(left), run(right)
                if isinstance(op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
                    raise ExprError(f"{text!r}: division by zero")
                if isinstance(op, ast.Pow) and abs(b) > MAX_POWER:
                    raise ExprError(f"{text!r}: exponent {b:g} is too large")
                return float(BINOPS[type(op)](a, b))
            case ast.UnaryOp(op=op, operand=operand):
                v = run(operand)
                if isinstance(op, ast.Not):
                    return float(not v)
                return -v if isinstance(op, ast.USub) else v
            case ast.Compare(left=left, ops=ops, comparators=rest):
                a = run(left)
                for o, n in zip(ops, rest):
                    b = run(n)
                    if not COMPARE[type(o)](a, b):
                        return 0.0
                    a = b
                return 1.0
            case ast.BoolOp(op=op, values=items):
                if isinstance(op, ast.And):
                    return float(all(run(n) for n in items))
                return float(any(run(n) for n in items))
            case ast.IfExp(test=test, body=body, orelse=orelse):
                return run(body) if run(test) else run(orelse)
            case ast.Call(func=ast.Name(id=name), args=args):
                try:
                    return float(FUNCS[name](*(run(a) for a in args)))
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ExprError(f"{text!r}: {name}(): {exc}") from exc
        raise ExprError(f"{text!r}: cannot evaluate")

    return run(_parse(text))
