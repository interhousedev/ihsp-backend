"""A parser for the literal subset of OpenUI Lang that the assistants may write.

A program is a list of statements `identifier = Expression`. Expressions are
component calls `Name(arg, ...)` (positional arguments), strings, numbers,
`true`/`false`/`null`, arrays, objects `{key: value}` and references to other
statements. State (`$x`), built-in calls (`@Fn`), queries, actions and operators of
the full language are refused: the chat renders data, it runs nothing.
"""

import json
import re
from dataclasses import dataclass
from typing import Union

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>[()\[\]{},:=])
    """,
    re.VERBOSE,
)


class OpenUiSyntaxError(ValueError):
    """The block is not valid OpenUI Lang (of the supported subset)."""


@dataclass(frozen=True, slots=True)
class Call:
    """A component call."""

    name: str
    args: tuple["Node", ...]


@dataclass(frozen=True, slots=True)
class Ref:
    """A reference to another statement."""

    name: str


@dataclass(frozen=True, slots=True)
class Lit:
    """A string, number, boolean or null."""

    value: str | float | bool | None


@dataclass(frozen=True, slots=True)
class Arr:
    """An array."""

    items: tuple["Node", ...]


@dataclass(frozen=True, slots=True)
class Obj:
    """An object with identifier or string keys."""

    entries: tuple[tuple[str, "Node"], ...]


Node = Union[Call, Ref, Lit, Arr, Obj]
_KEYWORDS = {"true": True, "false": False, "null": None}


def _tokens(source: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    pos = 0
    while pos < len(source):
        match = _TOKEN.match(source, pos)
        if match is None:
            raise OpenUiSyntaxError(
                f"unsupported character {source[pos]!r} at offset {pos} "
                "(only component calls, literals, arrays, objects and references)"
            )
        kind = match.lastgroup or ""
        if kind != "ws":
            found.append((kind, match.group()))
        pos = match.end()
    return found


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.at = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self, text: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None:
            raise OpenUiSyntaxError("unexpected end of block")
        if text is not None and token[1] != text:
            raise OpenUiSyntaxError(f"expected {text!r}, found {token[1]!r}")
        self.at += 1
        return token

    def statements(self) -> dict[str, Node]:
        program: dict[str, Node] = {}
        while self.peek() is not None:
            kind, name = self.take()
            if kind != "name" or name in _KEYWORDS:
                raise OpenUiSyntaxError(f"a statement must start with a name: {name!r}")
            self.take("=")
            if name in program:
                raise OpenUiSyntaxError(f"{name} is defined twice")
            program[name] = self.expression()
        return program

    def expression(self) -> Node:
        kind, text = self.take()
        if kind == "string":
            return Lit(json.loads(text))
        if kind == "number":
            return Lit(float(text))
        if kind == "name":
            return self.named(text)
        if text == "[":
            return Arr(tuple(self.sequence("]")))
        if text == "{":
            return self.obj()
        raise OpenUiSyntaxError(f"unexpected {text!r}")

    def named(self, text: str) -> Node:
        if text in _KEYWORDS:
            return Lit(_KEYWORDS[text])
        token = self.peek()
        if token is not None and token[1] == "(":
            self.take("(")
            return Call(text, tuple(self.sequence(")")))
        return Ref(text)

    def sequence(self, close: str) -> list[Node]:
        items: list[Node] = []
        while True:
            token = self.peek()
            if token is not None and token[1] == close:
                self.take()
                return items
            items.append(self.expression())
            token = self.peek()
            if token is not None and token[1] == ",":
                self.take()

    def obj(self) -> Obj:
        entries: list[tuple[str, Node]] = []
        while True:
            kind, text = self.take()
            if text == "}":
                return Obj(tuple(entries))
            if text == ",":
                continue
            if kind not in ("name", "string"):
                raise OpenUiSyntaxError(f"bad object key {text!r}")
            key = json.loads(text) if kind == "string" else text
            self.take(":")
            entries.append((key, self.expression()))


def parse_program(source: str) -> dict[str, Node]:
    """Parse a block into its statements by name; raise `OpenUiSyntaxError`."""
    return _Parser(_tokens(source)).statements()
