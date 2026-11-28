"""Club media: albums, media, reports, upload blocks, per-club limits, event cover.

Revision ID: activities_0005
Revises: activities_0004
Create Date: 2026-11-28 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "activities_0005"
down_revision: str | Sequence[str] | None = "activities_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the media tables and the new club and event columns."""
    op.execute("""
ALTER TABLE activities.activities_clubs
    ADD COLUMN media_photo_max_bytes BIGINT,
    ADD COLUMN media_video_max_bytes BIGINT,
    ADD COLUMN media_quota_bytes BIGINT
""")
    op.execute(
        "ALTER TABLE activities.activities_events ADD COLUMN cover_media_id UUID"
    )
    op.execute("""
CREATE TABLE activities.activities_albums (
    id UUID NOT NULL,
    club_id UUID NOT NULL,
    event_id UUID,
    parent_id UUID,
    title VARCHAR(120) NOT NULL,
    description VARCHAR(1000),
    event_date DATE,
    visibility VARCHAR(16) DEFAULT 'school' NOT NULL,
    allow_download BOOLEAN DEFAULT true NOT NULL,
    member_uploads BOOLEAN DEFAULT false NOT NULL,
    cover_media_id UUID,
    source_ref VARCHAR(80),
    created_by UUID,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_activities_albums PRIMARY KEY (id),
    CONSTRAINT ck_activities_albums_visibility
        CHECK (visibility IN ('members', 'school'))
)
""")
    op.execute(
        "CREATE INDEX ix_activities_albums_club"
        " ON activities.activities_albums (club_id, parent_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_activities_albums_event_root"
        " ON activities.activities_albums (event_id)"
        " WHERE parent_id IS NULL AND event_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_activities_albums_event_date"
        " ON activities.activities_albums (club_id, event_date DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_activities_albums_source_ref"
        " ON activities.activities_albums (source_ref)"
        " WHERE source_ref IS NOT NULL"
    )
    op.execute("""
CREATE TABLE activities.activities_media (
    id UUID NOT NULL,
    club_id UUID NOT NULL,
    usage VARCHAR(16) NOT NULL,
    album_id UUID,
    event_id UUID,
    announcement_id UUID,
    kind VARCHAR(8) NOT NULL,
    status VARCHAR(12) NOT NULL,
    original_file_id UUID,
    thumb_file_id UUID,
    preview_file_id UUID,
    poster_file_id UUID,
    byte_size BIGINT DEFAULT 0 NOT NULL,
    content_sha256 VARCHAR(64) DEFAULT '' NOT NULL,
    width INTEGER,
    height INTEGER,
    duration_ms INTEGER,
    caption VARCHAR(300),
    position INTEGER DEFAULT 0 NOT NULL,
    consent_attested BOOLEAN DEFAULT false NOT NULL,
    imported BOOLEAN DEFAULT false NOT NULL,
    source_ref VARCHAR(80),
    uploaded_by UUID,
    hidden_reason VARCHAR(300),
    hidden_by UUID,
    hidden_source VARCHAR(10),
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_activities_media PRIMARY KEY (id),
    CONSTRAINT ck_activities_media_usage
        CHECK (usage IN ('staged', 'album', 'event_cover', 'announcement')),
    CONSTRAINT ck_activities_media_kind CHECK (kind IN ('photo', 'video')),
    CONSTRAINT ck_activities_media_status
        CHECK (status IN (
            'uploading', 'processing', 'ready', 'failed', 'hidden', 'deleted'
        )),
    CONSTRAINT ck_activities_media_hidden_source
        CHECK (hidden_source IN ('moderator', 'uploader', 'report')),
    CONSTRAINT ck_activities_media_target CHECK (
        (usage = 'staged' AND album_id IS NULL AND event_id IS NULL
            AND announcement_id IS NULL)
        OR (usage = 'album' AND album_id IS NOT NULL AND event_id IS NULL
            AND announcement_id IS NULL)
        OR (usage = 'event_cover' AND event_id IS NOT NULL AND album_id IS NULL
            AND announcement_id IS NULL)
        OR (usage = 'announcement' AND announcement_id IS NOT NULL
            AND album_id IS NULL AND event_id IS NULL)
    )
)
""")
    op.execute(
        "CREATE INDEX ix_activities_media_album"
        " ON activities.activities_media (album_id, position, id)"
    )
    op.execute(
        "CREATE INDEX ix_activities_media_club ON activities.activities_media (club_id)"
    )
    op.execute(
        "CREATE INDEX ix_activities_media_event"
        " ON activities.activities_media (event_id)"
    )
    op.execute(
        "CREATE INDEX ix_activities_media_announcement"
        " ON activities.activities_media (announcement_id)"
    )
    op.execute(
        "CREATE INDEX ix_activities_media_status"
        " ON activities.activities_media (status, updated_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_activities_media_album_sha"
        " ON activities.activities_media (album_id, content_sha256)"
        " WHERE album_id IS NOT NULL AND status <> 'deleted'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_activities_media_source_ref"
        " ON activities.activities_media (source_ref)"
        " WHERE source_ref IS NOT NULL"
    )
    op.execute("""
CREATE TABLE activities.activities_media_reports (
    id UUID NOT NULL,
    media_id UUID NOT NULL,
    reporter_id UUID NOT NULL,
    is_subject BOOLEAN NOT NULL,
    reason VARCHAR(500) DEFAULT '' NOT NULL,
    status VARCHAR(10) DEFAULT 'open' NOT NULL,
    resolved_by UUID,
    resolved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_activities_media_reports PRIMARY KEY (id),
    CONSTRAINT uq_activities_media_reports_media_id UNIQUE (media_id, reporter_id),
    CONSTRAINT ck_activities_media_reports_status
        CHECK (status IN ('open', 'upheld', 'dismissed'))
)
""")
    op.execute(
        "CREATE INDEX ix_activities_media_reports_status"
        " ON activities.activities_media_reports (status, created_at)"
    )
    op.execute("""
CREATE TABLE activities.activities_media_blocks (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    club_id UUID,
    reason VARCHAR(300) DEFAULT '' NOT NULL,
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_activities_media_blocks PRIMARY KEY (id)
)
""")
    op.execute(
        "CREATE UNIQUE INDEX uq_activities_media_blocks_club"
        " ON activities.activities_media_blocks (user_id, club_id)"
        " WHERE club_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_activities_media_blocks_global"
        " ON activities.activities_media_blocks (user_id) WHERE club_id IS NULL"
    )


def downgrade() -> None:
    """Drop the media tables and the new columns."""
    op.execute("DROP TABLE activities.activities_media_blocks")
    op.execute("DROP TABLE activities.activities_media_reports")
    op.execute("DROP TABLE activities.activities_media")
    op.execute("DROP TABLE activities.activities_albums")
    op.execute("ALTER TABLE activities.activities_events DROP COLUMN cover_media_id")
    op.execute("""
ALTER TABLE activities.activities_clubs
    DROP COLUMN media_photo_max_bytes,
    DROP COLUMN media_video_max_bytes,
    DROP COLUMN media_quota_bytes
""")
