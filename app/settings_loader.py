"""Loading `Settings` from the environment and layered env files, with clear errors.

    IHSP_ENV_FILE=materials/dev.env,?.env.local

`IHSP_ENV_FILE` is a comma list of dotenv files. Later files win over earlier ones
and the process environment wins over all of them. A `?` before a name makes the
file optional; a required file that is missing stops the start.
"""

import os
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args, get_origin

import structlog
from dotenv import dotenv_values
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from app.settings import Settings

log = structlog.get_logger(__name__)

ENV_PREFIX = "IHSP_"
ENV_FILE_VARIABLE = "IHSP_ENV_FILE"
# IHSP_ variables other settings classes or tools read: not an error for `Settings`.
NOT_SETTINGS = (
    ENV_FILE_VARIABLE,
    "IHSP_WEB_",
    "IHSP_HYDRA__MINIAPP_",
    "IHSP_BOT_USERNAME",
    "IHSP_STORAGE_ORIGIN",
)
SECRET_WORDS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PEM")
VALUE_SHOWN_CHARS = 60


class SettingsError(ValueError):
    """The environment cannot become `Settings`; the message lists the bad variables."""


def parse_env_files(raw: str | None) -> list[Path]:
    """The existing files of an `IHSP_ENV_FILE` comma list, in reading order.

    Raises:
        SettingsError: A required file (no leading `?`) does not exist.
    """
    files: list[Path] = []
    missing: list[str] = []
    for item in (raw or "").split(","):
        name = item.strip()
        optional = name.startswith("?")
        name = name.removeprefix("?").strip()
        if not name:
            continue
        path = Path(name).expanduser()
        if path.is_file():
            files.append(path)
        elif not optional:
            missing.append(name)
    if missing:
        raise SettingsError(
            f"{ENV_FILE_VARIABLE}: file not found: {', '.join(missing)} "
            "(put ? before a name to make a file optional)"
        )
    return files


def variable_name(loc: Iterable[int | str]) -> str:
    """The environment variable of a pydantic error location."""
    parts = [str(part).upper() for part in loc if part != "[key]"]
    return ENV_PREFIX + "__".join(parts)


def _shown(name: str, value: object) -> str:
    if any(word in name for word in SECRET_WORDS):
        return ""
    text = repr(value)
    if len(text) > VALUE_SHOWN_CHARS:
        text = text[:VALUE_SHOWN_CHARS] + "..."
    return f" (got {text})"


def describe(error: ValidationError) -> str:
    """One line per bad variable: `IHSP_X__Y: what is wrong (got 'value')`."""
    lines = []
    for item in error.errors(include_url=False):
        loc = item["loc"]
        message = str(item["msg"]).removeprefix("Value error, ")
        if not loc:
            lines.append(f"  {message}")
            continue
        name = variable_name(loc)
        lines.append(f"  {name}: {message}{_shown(name, item.get('input'))}")
    return f"invalid settings ({len(lines)}):\n" + "\n".join(lines)


def _section(annotation: Any) -> type[BaseModel] | None:  # a pydantic annotation
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _key_is_valid(key_type: Any, key: str) -> bool:  # a pydantic annotation
    if isinstance(key_type, type) and issubclass(key_type, Enum):
        return key in {str(member.value).lower() for member in key_type}
    return True


def path_exists(parts: list[str], model: type[BaseModel] | None = None) -> bool:
    """True when `section__field` parts name a setting (dict keys are checked too)."""
    if model is None:
        from app.settings import Settings

        model = Settings
    field = model.model_fields.get(parts[0])
    if field is None:
        return False
    rest, annotation = parts[1:], field.annotation
    if get_origin(annotation) is dict:
        key_type, annotation = get_args(annotation)
        if rest and not _key_is_valid(key_type, rest[0]):
            return False
        rest = rest[1:]
    if not rest:
        return True
    section = _section(annotation)
    return section is not None and path_exists(rest, section)


def setting_exists(variable: str) -> bool:
    """True when `IHSP_SECTION__FIELD` names a setting of `Settings`."""
    if not variable.upper().startswith(ENV_PREFIX):
        return False
    return path_exists(variable[len(ENV_PREFIX) :].lower().split("__"))


def unknown_variables(names: Iterable[str]) -> list[str]:
    """The `IHSP_` names that are no setting (typos) and no known outside variable."""
    unknown = {
        name
        for name in (n.upper() for n in names)
        if name.startswith(ENV_PREFIX)
        and not name.startswith(NOT_SETTINGS)
        and not setting_exists(name)
    }
    return sorted(unknown)


def _present_names(files: list[Path]) -> set[str]:
    names = set(os.environ)
    for path in files:
        names.update(key for key in dotenv_values(path) if key)
    return names


def load_settings() -> "Settings":
    """Build `Settings` from the layered env files and the process environment.

    Raises:
        SettingsError: A required file is missing or settings are invalid; the
            message names every bad variable.
    """
    from app.settings import Settings

    files = parse_env_files(os.environ.get(ENV_FILE_VARIABLE))
    try:
        settings = Settings(_env_file=tuple(files) or None)
    except ValidationError as exc:
        raise SettingsError(describe(exc)) from exc
    unknown = unknown_variables(_present_names(files))
    if unknown:
        log.warning("settings.unknown_variables", variables=unknown)
    return settings
