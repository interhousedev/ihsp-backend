"""Sharing notebooks: grants, links and attached source sets.

Revision ID: notebooks_0014
Revises: notebooks_0013
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0014"
down_revision: str | Sequence[str] | None = "notebooks_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTEBOOK = "notebooks.notebooks.id"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notebook_shares",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("via", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "via IN ('direct', 'link')", name=op.f("ck_notebook_shares_via")
        ),
        sa.ForeignKeyConstraint(
            ["notebook_id"],
            [NOTEBOOK],
            name=op.f("fk_notebook_shares_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "notebook_id", "user_id", name=op.f("pk_notebook_shares")
        ),
        schema="notebooks",
    )
    op.create_index(
        "ix_notebook_shares_user_id", "notebook_shares", ["user_id"], schema="notebooks"
    )
    op.create_table(
        "notebook_share_links",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["notebook_id"],
            [NOTEBOOK],
            name=op.f("fk_notebook_share_links_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("notebook_id", name=op.f("pk_notebook_share_links")),
        sa.UniqueConstraint(
            "token_hash", name=op.f("uq_notebook_share_links_token_hash")
        ),
        schema="notebooks",
    )
    op.create_table(
        "notebook_linked_sets",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("linked_notebook_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "notebook_id <> linked_notebook_id",
            name=op.f("ck_notebook_linked_sets_not_self"),
        ),
        sa.ForeignKeyConstraint(
            ["notebook_id"],
            [NOTEBOOK],
            name=op.f("fk_notebook_linked_sets_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linked_notebook_id"],
            [NOTEBOOK],
            name=op.f("fk_notebook_linked_sets_linked_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "notebook_id", "linked_notebook_id", name=op.f("pk_notebook_linked_sets")
        ),
        schema="notebooks",
    )
    op.create_index(
        "ix_notebook_linked_sets_linked_notebook_id",
        "notebook_linked_sets",
        ["linked_notebook_id"],
        schema="notebooks",
    )


def downgrade() -> None:
    """Downgrade schema (every grant, link and attached set is lost)."""
    op.drop_table("notebook_linked_sets", schema="notebooks")
    op.drop_table("notebook_share_links", schema="notebooks")
    op.drop_table("notebook_shares", schema="notebooks")
