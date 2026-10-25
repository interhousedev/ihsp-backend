"""Exercise kind: Studio practice sets with passages and typed questions.

Studio outputs get the `exercise` kind: practice sets with a passage (stimulus) and
questions of several types (IELTS, SAT, AP style).

Revision ID: notebooks_0012
Revises: notebooks_0011
Create Date: 2026-10-26 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0012"
down_revision: str | Sequence[str] | None = "notebooks_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "report",
    "mind_map",
    "flashcards",
    "quiz",
    "data_table",
    "slides",
    "infographic",
    "audio_overview",
    "course_plan",
    "lesson_draft",
)
NEW_KINDS = (*OLD_KINDS, "exercise")


def _in_list(column: str, values: Sequence[str]) -> str:
    """The CHECK text of a VARCHAR enumeration (as `sa.Enum` writes it)."""
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({listed})"


def _replace_check(condition: str) -> None:
    """Drop the kind CHECK of notebooks.artifacts and create it with `condition`."""
    name = op.f("ck_artifacts_kind")
    op.drop_constraint(name, "artifacts", schema="notebooks", type_="check")
    op.create_check_constraint(name, "artifacts", condition, schema="notebooks")


def upgrade() -> None:
    """Allow the exercise kind."""
    _replace_check(_in_list("kind", NEW_KINDS))


def downgrade() -> None:
    """Remove the exercise outputs and the kind."""
    op.execute("DELETE FROM notebooks.artifacts WHERE kind = 'exercise'")
    _replace_check(_in_list("kind", OLD_KINDS))
