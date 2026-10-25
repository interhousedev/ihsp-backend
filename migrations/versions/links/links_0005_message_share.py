"""Shares of one assistant answer (the bot's "See visualization" button).

A new link kind `message`: `target_id` is the chat, `snapshot_seq` the answer's
seq and `expires_at` (already per share) is set to seven days. The kind check and
the share-target check list it; existing rows stay valid. Downgrading deletes the
message links and puts the old checks back.

Revision ID: links_0005
Revises: links_0004
Create Date: 2026-10-26 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "links_0005"
down_revision: str | Sequence[str] | None = "links_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = ("url", "file", "chat", "flashcard_set", "artifact")
NEW_KINDS = (*OLD_KINDS, "message")
OLD_SHARES = ("chat", "flashcard_set", "artifact")
NEW_SHARES = (*OLD_SHARES, "message")


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
    _replace_checks(NEW_KINDS, NEW_SHARES)


def downgrade() -> None:
    """Downgrade schema (message links go)."""
    op.execute("DELETE FROM links.links WHERE kind = 'message'")
    _replace_checks(OLD_KINDS, OLD_SHARES)
