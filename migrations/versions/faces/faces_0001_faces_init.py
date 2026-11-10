"""faces init: face profiles, entrance devices, their calls and passages.

Revision ID: faces_0001
Revises:
Create Date: 2026-11-10 10:00:00.000000

Photos are files of the files module and users are identity users (no
cross-schema foreign keys). Calls and passages are purged after 7 days.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "faces_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("faces",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the schema and the tables."""
    op.execute("CREATE SCHEMA IF NOT EXISTS faces")
    op.execute("""
        CREATE TABLE faces.face_profiles (
            user_id uuid NOT NULL,
            embedding real[] NOT NULL,
            photo_file_id uuid NOT NULL,
            uploaded_by uuid NOT NULL,
            locked boolean NOT NULL DEFAULT false,
            updated_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_face_profiles PRIMARY KEY (user_id)
        )
        """)
    op.execute("""
        CREATE TABLE faces.devices (
            id uuid NOT NULL,
            name varchar(80) NOT NULL,
            key_prefix varchar(32) NOT NULL,
            key_hash varchar(64) NOT NULL,
            created_by uuid NOT NULL,
            created_at timestamptz NOT NULL,
            revoked_at timestamptz,
            last_used_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_devices PRIMARY KEY (id)
        )
        """)
    op.execute("CREATE UNIQUE INDEX uq_devices_key_hash ON faces.devices (key_hash)")
    op.execute("""
        CREATE TABLE faces.device_calls (
            id uuid NOT NULL,
            device_id uuid NOT NULL,
            at timestamptz NOT NULL,
            status varchar(16) NOT NULL,
            matched_user_id uuid,
            excused boolean,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_device_calls PRIMARY KEY (id),
            CONSTRAINT ck_device_calls_status CHECK (status IN ('matched',
                'no_match', 'no_face', 'multiple_faces'))
        )
        """)
    op.execute(
        "CREATE INDEX ix_device_calls_device_id_at "
        "ON faces.device_calls (device_id, at)"
    )
    op.execute("CREATE INDEX ix_device_calls_at ON faces.device_calls (at)")
    op.execute("""
        CREATE TABLE faces.passages (
            id uuid NOT NULL,
            device_id uuid NOT NULL,
            user_id uuid NOT NULL,
            at timestamptz NOT NULL,
            direction varchar(3) NOT NULL,
            excused boolean NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_passages PRIMARY KEY (id),
            CONSTRAINT ck_passages_direction CHECK (direction IN ('in', 'out'))
        )
        """)
    op.execute("CREATE INDEX ix_passages_at ON faces.passages (at)")
    op.execute("CREATE INDEX ix_passages_user_id_at ON faces.passages (user_id, at)")


def downgrade() -> None:
    """Drop the schema."""
    op.execute("DROP SCHEMA IF EXISTS faces CASCADE")
