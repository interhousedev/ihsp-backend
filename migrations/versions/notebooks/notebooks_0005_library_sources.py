"""Library books and notes as sources.

Two new kinds of source: `library_item` (a book or material of the library, whole or
a page range) and `library_notes` (the student's own highlights and notes in it). The
check constraint on `sources.kind` lists them; existing rows stay valid. Downgrading
deletes the sources of the two kinds (and the shared-document aliases of library
chapters) and puts the old constraint back.

Revision ID: notebooks_0005
Revises: notebooks_0004
Create Date: 2026-10-09 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0005"
down_revision: str | Sequence[str] | None = "notebooks_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "file",
    "chat",
    "lesson_resource",
    "flashcard_set",
    "lms_step",
    "text",
    "note",
    "url",
    "web_result",
)
LIBRARY_KINDS = ("library_item", "library_notes")
NEW_KINDS = (*OLD_KINDS, *LIBRARY_KINDS)
CONSTRAINT = "ck_sources_kind"


def _in_list(column: str, values: Sequence[str]) -> str:
    """The CHECK text of a VARCHAR enumeration (as `sa.Enum` writes it)."""
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({listed})"


def _replace_kind_check(kinds: Sequence[str]) -> None:
    """Drop the CHECK constraint of `sources.kind` and create it with `kinds`."""
    op.drop_constraint(op.f(CONSTRAINT), "sources", schema="notebooks", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), "sources", _in_list("kind", kinds), schema="notebooks"
    )


def upgrade() -> None:
    """Upgrade schema."""
    _replace_kind_check(NEW_KINDS)


def downgrade() -> None:
    """Downgrade schema (library sources and the aliases of their texts go)."""
    op.execute("DELETE FROM notebooks.document_aliases WHERE alias LIKE 'library:%'")
    op.execute(f"DELETE FROM notebooks.sources WHERE {_in_list('kind', LIBRARY_KINDS)}")
    _replace_kind_check(OLD_KINDS)
