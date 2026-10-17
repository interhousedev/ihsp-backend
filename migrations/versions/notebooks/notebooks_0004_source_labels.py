"""topic labels of sources

A notebook has up to 12 topic labels (`source_labels`: name, emoji, `origin` auto or
manual, one name once per notebook whatever its case); a source carries some of them
(`source_label_links`, with its own `origin`, so a link set by the student is never
replaced by an automatic run). `source_label_runs` holds the state of the automatic
labeling: one row per notebook that ever ran it.

Revision ID: notebooks_0004
Revises: notebooks_0003
Create Date: 2026-10-09 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0004"
down_revision: str | Sequence[str] | None = "notebooks_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _origin() -> sa.Enum:
    """The `origin` column type of labels and links (VARCHAR plus CHECK)."""
    return sa.Enum(
        "auto",
        "manual",
        name="origin",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "source_labels",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("origin", _origin(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["notebook_id"],
            ["notebooks.notebooks.id"],
            name=op.f("fk_source_labels_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_labels")),
        schema="notebooks",
    )
    op.create_index(
        "uq_source_labels_notebook_id_lower_name",
        "source_labels",
        ["notebook_id", sa.literal_column("lower(name)")],
        unique=True,
        schema="notebooks",
    )
    op.create_index(
        "ix_source_labels_notebook_id_position",
        "source_labels",
        ["notebook_id", "position"],
        unique=False,
        schema="notebooks",
    )
    op.create_table(
        "source_label_links",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("label_id", sa.Uuid(), nullable=False),
        sa.Column("origin", _origin(), nullable=False),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["notebooks.source_labels.id"],
            name=op.f("fk_source_label_links_label_id_source_labels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["notebooks.sources.id"],
            name=op.f("fk_source_label_links_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "source_id", "label_id", name=op.f("pk_source_label_links")
        ),
        schema="notebooks",
    )
    op.create_index(
        "ix_source_label_links_label_id",
        "source_label_links",
        ["label_id"],
        unique=False,
        schema="notebooks",
    )
    op.create_table(
        "source_label_runs",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "idle",
                "running",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'idle'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=40), nullable=True),
        sa.Column("started_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["notebook_id"],
            ["notebooks.notebooks.id"],
            name=op.f("fk_source_label_runs_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("notebook_id", name=op.f("pk_source_label_runs")),
        schema="notebooks",
    )


def downgrade() -> None:
    """Downgrade schema (labels and their links are deleted)."""
    op.drop_table("source_label_runs", schema="notebooks")
    op.drop_index(
        "ix_source_label_links_label_id",
        table_name="source_label_links",
        schema="notebooks",
    )
    op.drop_table("source_label_links", schema="notebooks")
    op.drop_index(
        "ix_source_labels_notebook_id_position",
        table_name="source_labels",
        schema="notebooks",
    )
    op.drop_index(
        "uq_source_labels_notebook_id_lower_name",
        table_name="source_labels",
        schema="notebooks",
    )
    op.drop_table("source_labels", schema="notebooks")
