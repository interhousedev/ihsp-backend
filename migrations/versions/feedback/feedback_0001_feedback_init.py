"""feedback init: platform feedback items and administrators' responses.

Revision ID: feedback_0001
Revises:
Create Date: 2026-10-25 10:00:00.000000

Attachments are file ids of the files module (no cross-schema foreign keys).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "feedback_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("feedback",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the schema, the tables and their indexes."""
    op.execute("CREATE SCHEMA IF NOT EXISTS feedback")
    op.execute("""
        CREATE TABLE feedback.items (
            id uuid NOT NULL,
            reporter_id uuid NOT NULL,
            kind varchar(16) NOT NULL,
            area varchar(16) NOT NULL,
            title varchar(120) NOT NULL,
            description text NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'new',
            source varchar(8) NOT NULL,
            page_url varchar(500),
            attachment_file_ids uuid[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_items PRIMARY KEY (id),
            CONSTRAINT ck_items_kind CHECK (kind IN ('idea', 'bug', 'other')),
            CONSTRAINT ck_items_area CHECK (area IN ('id', 'my', 'staff', 'admin',
                'lms', 'library', 'share', 'bot', 'ai', 'notebooks', 'mail',
                'other')),
            CONSTRAINT ck_items_status CHECK (status IN ('new', 'in_review',
                'planned', 'done', 'rejected')),
            CONSTRAINT ck_items_source CHECK (source IN ('web', 'bot'))
        )
        """)
    op.execute(
        "CREATE INDEX ix_items_reporter_id_created_at "
        "ON feedback.items (reporter_id, created_at)"
    )
    op.execute("CREATE INDEX ix_items_created_at_id ON feedback.items (created_at, id)")
    op.execute("CREATE INDEX ix_items_status ON feedback.items (status)")
    op.execute("""
        CREATE TABLE feedback.responses (
            id uuid NOT NULL,
            feedback_id uuid NOT NULL,
            author_id uuid NOT NULL,
            text text NOT NULL,
            channels varchar(16)[] NOT NULL DEFAULT '{}',
            deliveries jsonb NOT NULL DEFAULT '[]'::jsonb,
            attachment_file_ids uuid[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_responses PRIMARY KEY (id),
            CONSTRAINT fk_responses_feedback_id_items FOREIGN KEY (feedback_id)
                REFERENCES feedback.items (id) ON DELETE CASCADE
        )
        """)
    op.execute(
        "CREATE INDEX ix_responses_feedback_id_created_at "
        "ON feedback.responses (feedback_id, created_at)"
    )


def downgrade() -> None:
    """Drop the schema with its tables."""
    op.execute("DROP SCHEMA feedback CASCADE")
