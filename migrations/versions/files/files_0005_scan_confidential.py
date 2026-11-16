"""scan status, confidential flag and owner kind of files

Revision ID: files_0005
Revises: files_0004
Create Date: 2026-11-01 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "files_0005"
down_revision: str | Sequence[str] | None = "files_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "files",
        sa.Column(
            "scan_status",
            sa.String(length=9),
            server_default="unscanned",
            nullable=False,
        ),
        schema="files",
    )
    op.add_column(
        "files",
        sa.Column(
            "confidential", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        schema="files",
    )
    op.add_column(
        "files",
        sa.Column(
            "owner_kind",
            sa.String(length=11),
            server_default="user",
            nullable=False,
        ),
        schema="files",
    )
    op.create_check_constraint(
        op.f("ck_files_scan_status"),
        "files",
        "scan_status IN ('unscanned', 'pending', 'clean', 'infected', 'failed')",
        schema="files",
    )
    op.create_check_constraint(
        op.f("ck_files_owner_kind"),
        "files",
        "owner_kind IN ('user', 'institution')",
        schema="files",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("ck_files_owner_kind"), "files", schema="files", type_="check"
    )
    op.drop_constraint(
        op.f("ck_files_scan_status"), "files", schema="files", type_="check"
    )
    op.drop_column("files", "owner_kind", schema="files")
    op.drop_column("files", "confidential", schema="files")
    op.drop_column("files", "scan_status", schema="files")
