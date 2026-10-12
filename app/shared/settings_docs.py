"""Descriptions, types and defaults of the settings, read from the source.

The description of a variable is, in this order: `Field(description=...)`, the string
under the field (an attribute docstring), the `#` comment lines right above the field,
then its trailing `#` comment. The admin limits editor shows these texts, and a test
checks that every variable has one. The variables themselves are listed in
`materials/.env.sample`, one line each in field order.
"""

import ast
import inspect
import io
import textwrap
import tokenize
from dataclasses import dataclass
from enum import Enum
from types import NoneType, UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, SecretStr
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

NO_VALUE = "-"
DEPRECATED = "Deprecated"


@dataclass(frozen=True, slots=True)
class Row:
    """One environment variable."""

    variable: str
    type: str
    default: str
    description: str


def _comment_rows(source: str) -> dict[int, str]:
    """Trailing comments by line number (a comment after code, not on its own line)."""
    found: dict[int, str] = {}
    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        row, col = token.start
        if token.type == tokenize.COMMENT and lines[row - 1][:col].strip():
            found[row] = token.string.lstrip("#").strip()
    return found


def _leading_comment(lines: list[str], first_line: int) -> str:
    """The `#` lines directly above a field (1-based `first_line`), joined."""
    found: list[str] = []
    index = first_line - 2
    while index >= 0 and lines[index].strip().startswith("#"):
        found.append(lines[index].strip().lstrip("#").strip())
        index -= 1
    return " ".join(reversed(found))


def _docstring_after(body: list[ast.stmt], index: int) -> str | None:
    if index + 1 >= len(body):
        return None
    node = body[index + 1]
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        if isinstance(node.value.value, str):
            return " ".join(inspect.cleandoc(node.value.value).split())
    return None


def field_docs(model: type[BaseModel]) -> dict[str, str]:
    """Descriptions of the fields of a settings class, read from its source."""
    try:
        source = textwrap.dedent(inspect.getsource(model))
    except (OSError, TypeError):  # pragma: no cover - no source available
        return {}
    cls = ast.parse(source).body[0]
    if not isinstance(cls, ast.ClassDef):  # pragma: no cover
        return {}
    lines, trailing = source.splitlines(), _comment_rows(source)
    docs: dict[str, str] = {}
    for index, node in enumerate(cls.body):
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
            continue
        end = node.end_lineno or node.lineno
        side = [trailing[n] for n in range(node.lineno, end + 1) if n in trailing]
        text = _docstring_after(cls.body, index) or " ".join(
            part for part in (_leading_comment(lines, node.lineno), *side) if part
        )
        docs[node.target.id] = text
    return docs


def type_name(annotation: Any) -> str:  # a pydantic annotation
    """A short, readable type."""
    origin = get_origin(annotation)
    args = [arg for arg in get_args(annotation) if arg is not NoneType]
    if origin is Literal:
        return " | ".join(str(arg) for arg in args)
    if origin in (UnionType, Union):
        return " | ".join(type_name(arg) for arg in args)
    if origin in (tuple, list):
        return f"list of {type_name(args[0])}"
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return " | ".join(str(member.value) for member in annotation)
    if annotation is SecretStr:
        return "secret"
    return getattr(annotation, "__name__", str(annotation))


def default_text(field: FieldInfo) -> str:
    """The default as text; development secrets are not printed."""
    value = field.get_default(call_default_factory=True)
    if value is PydanticUndefined:
        return "required"
    if isinstance(value, SecretStr):
        return "(development value)" if value.get_secret_value() else NO_VALUE
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    if isinstance(value, tuple | list):
        return (
            ("`" + ",".join(str(item) for item in value) + "`") if value else NO_VALUE
        )
    if value is None or value == "":
        return NO_VALUE
    return f"`{value}`"


def _model_of(annotation: Any) -> type[BaseModel] | None:  # a pydantic annotation
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _key_placeholder(key_type: Any) -> str:  # a pydantic annotation
    name = getattr(key_type, "__name__", "key")
    return "<" + (name.removeprefix("Ai") or name).upper() + ">"


def collect(model: type[BaseModel], prefix: str = "") -> list[Row]:
    """Rows of a settings class and everything nested in it, in field order."""
    docs = field_docs(model)
    rows: list[Row] = []
    for name, field in model.model_fields.items():
        variable = f"{prefix}{name.upper()}"
        annotation = field.annotation
        if get_origin(annotation) is dict:
            key_type, annotation = get_args(annotation)
            variable += f"__{_key_placeholder(key_type)}"
        section = _model_of(annotation)
        if section is not None:
            rows.extend(collect(section, f"{variable}__"))
            continue
        description = field.description or docs.get(name, "")
        rows.append(
            Row(variable, type_name(annotation), default_text(field), description)
        )
    return rows
