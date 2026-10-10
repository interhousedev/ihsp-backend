"""Studio output shares.

A new link kind `artifact` (a public read-only view of a Studio output). The kind
check and the share-target check list it; existing rows stay valid. Downgrading
deletes the artifact links and puts the old checks back.

Revision ID: links_0002
Revises: links_0001
Create Date: 2026-10-10 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "links_0002"
down_revision: str | Sequence[str] | None = "links_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = ("url", "file", "chat", "flashcard_set")
NEW_KINDS = (*OLD_KINDS, "artifact")


def _in_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _replace_checks(kinds: Sequence[str], shares: Sequence[str]) -> None:
    for name in ("ck_links_kind", "ck_links_share_target"):
        op.drop_constraint(op.f(name), "links", schema="links", type_="check")
    op.create_check_constraint(
        op.f("ck_links_kind"), "links", f"kind IN ({_in_list(kinds)})", schema="links"
    )
    op.create_check_constraint(
        op.f("ck_links_share_target"),
        "links",
        f"(kind IN ({_in_list(shares)})) = (target_id IS NOT NULL)",
        schema="links",
    )


def upgrade() -> None:
    """Upgrade schema."""
    _replace_checks(NEW_KINDS, ("chat", "flashcard_set", "artifact"))


def downgrade() -> None:
    """Downgrade schema (artifact links go)."""
    op.execute("DELETE FROM links.links WHERE kind = 'artifact'")
    _replace_checks(OLD_KINDS, ("chat", "flashcard_set"))
