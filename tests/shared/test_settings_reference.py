"""docs/reference/settings.md is generated from the settings and must be current."""

import re

from app.settings import Settings
from app.settings_loader import setting_exists
from app.shared.settings_reference import (
    REFERENCE_PATH,
    REGENERATE,
    Row,
    collect,
    field_docs,
    render,
)

import pytest
from pydantic import BaseModel

pytestmark = pytest.mark.skipif(
    not REFERENCE_PATH.parent.is_dir(),
    reason="docs/ is not part of this checkout (the backend image)",
)


def test_the_reference_is_up_to_date() -> None:
    """Change a setting or its comment, then run `scripts/settings_reference.py`."""
    current = REFERENCE_PATH.read_text(encoding="utf-8")

    assert current == render(), f"settings.md is out of date: run `{REGENERATE}`"


def test_every_setting_is_in_the_reference_with_a_description() -> None:
    """The table has a row, type, default and text for each variable."""
    rows = collect(Settings)

    assert len(rows) > 150
    undocumented = [row.variable for row in rows if not row.description]
    assert undocumented == [], "add a comment or a docstring to these fields"
    assert all(row.type and row.default for row in rows)


def test_every_row_of_the_reference_is_a_real_variable() -> None:
    """The reference lists names the loader accepts (task names as <TASK>)."""
    for row in collect(Settings):
        variable = "IHSP_" + re.sub(r"<TASK>", "STUDIO_QUIZ", row.variable)
        assert setting_exists(variable), row.variable


def test_the_reference_covers_the_ai_and_feature_sections() -> None:
    """The new sections are in the file, with a row per task field."""
    text = render()

    assert "`IHSP_AI__DEFAULT__MODEL`" in text
    assert "`IHSP_AI__TASKS__<TASK>__FALLBACKS`" in text
    assert "`IHSP_FEATURES__NOTEBOOKS`" in text
    assert "`IHSP_LIMITS__AI_SESSION_TOKENS_STUDENT`" in text
    assert "`STUDIO_SLIDES_REVISE`" in text
    assert "IHSP_ENV_FILE" in text


def test_variables_of_other_agents_are_included_automatically() -> None:
    """Push, EMIS and app settings come from the same walk."""
    names = {row.variable for row in collect(Settings)}

    assert {"PUSH__ENABLED", "EMIS__IMPORT_TOPICS", "APP__LATEST"} <= names


def test_deprecated_variables_are_listed_together() -> None:
    """Old names are marked Deprecated in their section and in a closing table."""
    text = render()
    closing = text[text.index("## Deprecated variables") :]

    for name in ("OPENROUTER__MODEL_STUDENT", "LIMITS__AI_SMART_WEIGHT"):
        assert f"`IHSP_{name}`" in closing


def test_descriptions_come_from_docstrings_and_comments() -> None:
    """Attribute docstring first, then the comment lines above, then a trailing one."""

    class Example(BaseModel):
        a: int = 1
        """From the docstring."""

        # From the line
        # above.
        b: int = 2

        c: int = 3  # From the trailing comment

        d: int = 4

    docs = field_docs(Example)

    assert docs["a"] == "From the docstring."
    assert docs["b"] == "From the line above."
    assert docs["c"] == "From the trailing comment"
    assert docs["d"] == ""


def test_secrets_and_empty_defaults_are_not_printed() -> None:
    """Development secrets show as a note, unset values as a dash."""
    rows = {row.variable: row for row in collect(Settings)}

    assert rows["TOKENS__SERVICE_TOKEN"].default == "(development value)"
    assert rows["VAULT__ROLE_ID"].default == "-"
    assert "dev-service-token" not in render()
    assert isinstance(rows["ENV"], Row)
