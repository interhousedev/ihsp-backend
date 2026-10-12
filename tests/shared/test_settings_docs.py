"""Every setting has a description, a type and a default read from the source."""

import re

from app.settings import Settings
from app.settings_loader import setting_exists
from app.shared.settings_docs import DEPRECATED, Row, collect, field_docs

from pydantic import BaseModel


def test_every_setting_has_a_description() -> None:
    """Each variable has a row with a type, a default and a text."""
    rows = collect(Settings)

    assert len(rows) > 150
    undocumented = [row.variable for row in rows if not row.description]
    assert undocumented == [], "add a comment or a docstring to these fields"
    assert all(row.type and row.default for row in rows)


def test_every_row_is_a_real_variable() -> None:
    """The rows name variables the loader accepts (task names as <TASK>)."""
    for row in collect(Settings):
        variable = "IHSP_" + re.sub(r"<TASK>", "STUDIO_QUIZ", row.variable)
        assert setting_exists(variable), row.variable


def test_the_walk_covers_the_ai_and_feature_sections() -> None:
    """Nested sections and dict sections (per task) get a row per field."""
    names = {row.variable for row in collect(Settings)}

    assert "AI__DEFAULT__MODEL" in names
    assert "AI__TASKS__<TASK>__FALLBACKS" in names
    assert "FEATURES__NOTEBOOKS" in names
    assert "LIMITS__AI_SESSION_TOKENS_STUDENT" in names


def test_variables_of_other_agents_are_included_automatically() -> None:
    """Push, EMIS and app settings come from the same walk."""
    names = {row.variable for row in collect(Settings)}

    assert {"PUSH__ENABLED", "EMIS__IMPORT_TOPICS", "APP__LATEST"} <= names


def test_deprecated_variables_are_marked() -> None:
    """Old names say Deprecated in their description (still read, with a warning)."""
    rows = {row.variable: row for row in collect(Settings)}

    for name in ("OPENROUTER__MODEL_STUDENT", "LIMITS__AI_SMART_WEIGHT"):
        assert rows[name].description.startswith(DEPRECATED), name


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
    assert "dev-service-token" not in "".join(row.default for row in rows.values())
    assert isinstance(rows["ENV"], Row)
