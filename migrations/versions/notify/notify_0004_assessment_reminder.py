"""assessment reminder notification type

Revision ID: notify_0004
Revises: notify_0003
Create Date: 2026-10-08 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notify_0004"
down_revision: str | Sequence[str] | None = "notify_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = (
    "marks",
    "result_drop",
    "result_below",
    "lesson_resources",
    "lesson_prompt",
    "lesson_changed",
    "mail",
    "mail_bounced",
    "broadcast",
    "emis_reauth",
    "files_expiring",
    "telegram_linked",
    "otp_reset_requested",
    "login_failures",
    "account_closing",
    "mail_suspended",
    "sync_alert",
    "notebook_artifact_ready",
)
NEW_TYPES = (*OLD_TYPES, "assessment_reminder")
CONSTRAINT = "ck_notifications_type"


def _replace_type_column(types: tuple[str, ...]) -> None:
    """Resize ``type`` to the longest value and re-create its CHECK constraint."""
    op.execute(f"ALTER TABLE notify.notifications DROP CONSTRAINT {CONSTRAINT}")
    op.alter_column(
        "notifications",
        "type",
        existing_type=sa.String(),
        type_=sa.String(length=max(len(value) for value in types)),
        existing_nullable=False,
        schema="notify",
    )
    values = ", ".join(f"'{value}'" for value in types)
    op.execute(
        f"ALTER TABLE notify.notifications "
        f"ADD CONSTRAINT {CONSTRAINT} CHECK (type IN ({values}))"
    )


def upgrade() -> None:
    """Allow the ``assessment_reminder`` notification type."""
    _replace_type_column(NEW_TYPES)


def downgrade() -> None:
    """Forbid the type again; its rows are deleted, they cannot be kept."""
    op.execute("DELETE FROM notify.notifications WHERE type = 'assessment_reminder'")
    _replace_type_column(OLD_TYPES)
