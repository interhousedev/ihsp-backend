"""index files by checksum

EMIS materials with the same content share one stored file; the import looks the
file up by its SHA-256 (``checksum``, base64), which every row already has.

Revision ID: files_0003
Revises: files_0002
Create Date: 2026-10-17 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "files_0003"
down_revision: str | Sequence[str] | None = "files_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the checksum index."""
    op.create_index("ix_files_checksum", "files", ["checksum"], schema="files")


def downgrade() -> None:
    """Drop the checksum index."""
    op.drop_index("ix_files_checksum", table_name="files", schema="files")
