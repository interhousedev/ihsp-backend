"""media init: voice-over and video jobs.

Revision ID: media_0001
Revises:
Create Date: 2026-11-27 12:00:00.000000

Files are files of the files module; users and subjects belong to other modules
(no cross-schema foreign keys).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "media_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("media",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the schema and the table."""
    op.execute("CREATE SCHEMA IF NOT EXISTS media")
    op.execute("""
        CREATE TABLE media.media_jobs (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            kind varchar(24) NOT NULL,
            script jsonb NOT NULL,
            options jsonb NOT NULL,
            script_hash varchar(64) NOT NULL,
            subject_id uuid NOT NULL,
            group_id uuid,
            status varchar(16) NOT NULL,
            attempts integer NOT NULL DEFAULT 0,
            max_attempts integer NOT NULL DEFAULT 3,
            audio_file_id uuid,
            captions_file_id uuid,
            file_id uuid,
            storage_key varchar(300),
            segments jsonb NOT NULL DEFAULT '[]'::jsonb,
            duration_ms integer NOT NULL DEFAULT 0,
            error text,
            delivered boolean NOT NULL DEFAULT false,
            version integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_media_jobs PRIMARY KEY (id)
        )
        """)
    op.execute(
        "CREATE INDEX ix_media_jobs_owner_hash ON media.media_jobs "
        "(owner_id, script_hash)"
    )
    op.execute(
        "CREATE INDEX ix_media_jobs_owner_created ON media.media_jobs "
        "(owner_id, created_at)"
    )


def downgrade() -> None:
    """Drop the schema."""
    op.execute("DROP SCHEMA IF EXISTS media CASCADE")
