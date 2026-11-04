"""Projects: a named group of chats with their own files (ai.projects, project files).

Revision ID: ai_0006
Revises: ai_0005
Create Date: 2026-11-04 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_0006"
down_revision: str | Sequence[str] | None = "ai_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ai.projects and ai.project_files; chats may belong to a project."""
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "instructions", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        schema="ai",
    )
    op.create_index(
        "ix_projects_owner_id", "projects", ["owner_id"], unique=False, schema="ai"
    )
    op.create_table(
        "project_files",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["ai.projects.id"],
            name=op.f("fk_project_files_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id", "file_id", name=op.f("pk_project_files")),
        schema="ai",
    )
    op.create_index(
        "ix_project_files_file_id",
        "project_files",
        ["file_id"],
        unique=False,
        schema="ai",
    )
    op.add_column(
        "chats", sa.Column("project_id", sa.Uuid(), nullable=True), schema="ai"
    )
    op.create_foreign_key(
        "fk_chats_project_id_projects",
        "chats",
        "projects",
        ["project_id"],
        ["id"],
        source_schema="ai",
        referent_schema="ai",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_chats_project_id", "chats", ["project_id"], unique=False, schema="ai"
    )


def downgrade() -> None:
    """Drop the project link of chats and the project tables."""
    op.drop_index("ix_chats_project_id", table_name="chats", schema="ai")
    op.drop_constraint(
        "fk_chats_project_id_projects", "chats", schema="ai", type_="foreignkey"
    )
    op.drop_column("chats", "project_id", schema="ai")
    op.drop_index("ix_project_files_file_id", table_name="project_files", schema="ai")
    op.drop_table("project_files", schema="ai")
    op.drop_index("ix_projects_owner_id", table_name="projects", schema="ai")
    op.drop_table("projects", schema="ai")
