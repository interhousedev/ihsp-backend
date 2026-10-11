"""A tiny, safe evaluator of math expressions for formula and generated questions.

Only numbers, named variables, ``+ - * / % ** ^``, parentheses and a fixed set of
functions are allowed; nothing is ever executed with ``eval``.
"""

import ast
import math
import operator
import random
from collections.abc import Callable, Mapping, Sequence
from typing import Final

MAX_EXPRESSION_LENGTH: Final = 500
MAX_EXPONENT: Final = 100.0
SYMBOLIC_POINTS: Final = 12

_BINARY: Final[dict[type[ast.operator], Callable[[float, float], float]]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_FUNCTIONS: Final[dict[str, Callable[..., float]]] = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "exp": math.exp,
    "ln": math.log,
    "log": math.log10,
    "log10": math.log10,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
    "min": min,
    "max": max,
}
_CONSTANTS: Final = {"pi": math.pi, "e": math.e}


class ExpressionError(ValueError):
    """The expression is malformed, uses something not allowed or cannot be computed."""


def _parse(source: str) -> ast.expr:
    """Parse ``source`` into an expression tree (``^`` means power)."""
    if not source.strip() or len(source) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError("empty or too long")
    try:
        return ast.parse(source.strip().replace("^", "**"), mode="eval").body
    except SyntaxError as error:
        raise ExpressionError("syntax error") from error


def evaluate(source: str, variables: Mapping[str, float] | None = None) -> float:
    """Return the value of ``source`` with the given variables.

    Raises:
        ExpressionError: Syntax error, unknown name or function, or a math error.
    """
    scope = {**_CONSTANTS, **(variables or {})}
    try:
        result = _eval(_parse(source), scope)
    except (ArithmeticError, ValueError, TypeError) as error:
        if isinstance(error, ExpressionError):
            raise
        raise ExpressionError(str(error)) from error
    if not math.isfinite(result):
        raise ExpressionError("not finite")
    return float(result)


def _eval(node: ast.expr, scope: Mapping[str, float]) -> float:
    """Evaluate one node of the whitelisted grammar."""
    if isinstance(node, ast.Constant):
        return _constant(node)
    if isinstance(node, ast.Name):
        return _name(node, scope)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        return _unary(node, scope)
    if isinstance(node, ast.BinOp):
        return _binary(node, scope)
    if isinstance(node, ast.Call):
        return _call(node, scope)
    raise ExpressionError("not allowed")


def _constant(node: ast.Constant) -> float:
    """Return a number literal; booleans and other literals are not allowed."""
    if isinstance(node.value, bool) or not isinstance(node.value, int | float):
        raise ExpressionError("bad constant")
    return float(node.value)


def _name(node: ast.Name, scope: Mapping[str, float]) -> float:
    """Return the value of a variable or constant in scope."""
    if node.id not in scope:
        raise ExpressionError(f"unknown name {node.id}")
    return float(scope[node.id])


def _unary(node: ast.UnaryOp, scope: Mapping[str, float]) -> float:
    """Apply unary ``+`` or ``-`` (the caller allows only these)."""
    value = _eval(node.operand, scope)
    return -value if isinstance(node.op, ast.USub) else value


def _binary(node: ast.BinOp, scope: Mapping[str, float]) -> float:
    """Apply a binary operator; powers are bounded by ``MAX_EXPONENT``."""
    left = _eval(node.left, scope)
    right = _eval(node.right, scope)
    if isinstance(node.op, ast.Pow):
        if abs(right) > MAX_EXPONENT:
            raise ExpressionError("exponent too large")
        return float(left**right)
    operation = _BINARY.get(type(node.op))
    if operation is None:
        raise ExpressionError("operator not allowed")
    return float(operation(left, right))


def _call(node: ast.Call, scope: Mapping[str, float]) -> float:
    """Call one of the whitelisted functions with positional arguments only."""
    function = node.func
    if (
        not isinstance(function, ast.Name)
        or function.id not in _FUNCTIONS
        or node.keywords
    ):
        raise ExpressionError("not allowed")
    args = [_eval(arg, scope) for arg in node.args]
    return float(_FUNCTIONS[function.id](*args))


def is_valid(source: str, names: Sequence[str]) -> bool:
    """Return True if ``source`` evaluates with every name set to 1.5."""
    try:
        evaluate(source, dict.fromkeys(names, 1.5))
    except ExpressionError:
        return False
    return True


def equivalent(
    expected: str,
    given: str,
    names: Sequence[str],
    *,
    tolerance: float,
    seed: str,
    symbolic: bool,
) -> bool:
    """Compare two expressions by value at sample points.

    ``symbolic`` tests many pseudo-random points (an identity test: two different
    rational or polynomial expressions agree on all of them only with negligible
    chance); otherwise a few fixed points are tried. Points where either side is
    undefined are skipped, and at least three points must be comparable.
    """
    rng = random.Random(seed)
    count = SYMBOLIC_POINTS if symbolic else 5
    compared = 0
    for index in range(count):
        point = {
            name: rng.uniform(0.5, 4.0) if symbolic else (index + 1) * 0.5 + at * 0.37
            for at, name in enumerate(names)
        }
        try:
            want = evaluate(expected, point)
            got = evaluate(given, point)
        except ExpressionError:
            continue
        if abs(want - got) > tolerance * max(1.0, abs(want)):
            return False
        compared += 1
    return compared >= 3
