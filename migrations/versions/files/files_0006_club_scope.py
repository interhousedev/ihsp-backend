"""club scope for files.

Adds `club` to the allowed values of `files.files.scope` (photos and videos owned by
a club). The column is a `varchar(7)`, which already fits it.

Revision ID: files_0006
Revises: files_0005
Create Date: 2026-11-28 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "files_0006"
down_revision: str | Sequence[str] | None = "files_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SCOPES = "'student', 'staff', 'course', 'mail', 'system', 'library'"
NEW_SCOPES = OLD_SCOPES + ", 'club'"


def _set_scope_check(scopes: str) -> None:
    """Replace the check constraint of the scope column."""
    op.drop_constraint(op.f("ck_files_scope"), "files", schema="files", type_="check")
    op.create_check_constraint(
        op.f("ck_files_scope"), "files", f"scope IN ({scopes})", schema="files"
    )


def upgrade() -> None:
    """Upgrade schema."""
    _set_scope_check(NEW_SCOPES)


def downgrade() -> None:
    """Downgrade schema.

    Club file rows cannot exist without the new value, so they are deleted; their
    S3 objects must be removed by hand.
    """
    op.execute("DELETE FROM files.files WHERE scope = 'club'")
    _set_scope_check(OLD_SCOPES)
