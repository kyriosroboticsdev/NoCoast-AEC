"""A tiny, safe arithmetic evaluator for brick part expressions ("w - 0.1", "max(0.3, h / 2)").

Only numbers, parameter names, + - * /, unary minus, parentheses and min/max/abs are
allowed; anything else (attribute access, calls to other functions, comprehensions)
is rejected when the library is loaded, so a brick file can never run code.
"""

from __future__ import annotations

import ast
import operator
from functools import lru_cache

FUNCS = {"min": min, "max": max, "abs": abs}
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class ExprError(ValueError):
    pass


@lru_cache(maxsize=4096)
def _parse(text: str) -> ast.AST:
    try:
        tree = ast.parse(text, mode="eval").body
    except SyntaxError as exc:
        raise ExprError(f"bad expression {text!r}: {exc.msg}") from exc
    _validate(tree, text)
    return tree


def _validate(node: ast.AST, text: str) -> None:
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise ExprError(f"{text!r}: only numbers are allowed")
    elif isinstance(node, ast.Name):
        pass
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in BINOPS:
            raise ExprError(f"{text!r}: operator not allowed")
        _validate(node.left, text)
        _validate(node.right, text)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.UAdd)):
            raise ExprError(f"{text!r}: operator not allowed")
        _validate(node.operand, text)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords:
            raise ExprError(f"{text!r}: only min(), max() and abs() may be called")
        for arg in node.args:
            _validate(arg, text)
    else:
        raise ExprError(f"{text!r}: {type(node).__name__} is not allowed")


def names_in(text: str) -> set[str]:
    return {n.id for n in ast.walk(_parse(text)) if isinstance(n, ast.Name) and n.id not in FUNCS}


def evaluate(text: str, values: dict[str, float]) -> float:
    def run(node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise ExprError(f"{text!r}: unknown name '{node.id}'")
            return float(values[node.id])
        if isinstance(node, ast.BinOp):
            right = run(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise ExprError(f"{text!r}: division by zero")
            return BINOPS[type(node.op)](run(node.left), right)
        if isinstance(node, ast.UnaryOp):
            v = run(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Call):
            return float(FUNCS[node.func.id](*(run(a) for a in node.args)))
        raise ExprError(f"{text!r}: cannot evaluate")

    return run(_parse(text))
