"""Drop stored club contact messages: messages are relayed to Telegram, not kept.

Revision ID: activities_0004
Revises: activities_0003
Create Date: 2026-11-27 21:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "activities_0004"
down_revision: str | Sequence[str] | None = "activities_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the contact messages table (with the senders' personal data)."""
    op.execute("DROP TABLE activities.activities_contact_messages")


def downgrade() -> None:
    """Re-create the empty table."""
    op.execute("""
CREATE TABLE activities.activities_contact_messages (
	id UUID NOT NULL,
	club_id UUID NOT NULL,
	name VARCHAR(100) NOT NULL,
	email VARCHAR(320) NOT NULL,
	body TEXT NOT NULL,
	ip_hash VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	status VARCHAR(12) NOT NULL,
	copied_to_safeguarding BOOLEAN NOT NULL,
	replied_by UUID,
	replied_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_activities_contact_messages PRIMARY KEY (id)
)
""")
