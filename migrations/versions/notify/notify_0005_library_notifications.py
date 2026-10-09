"""library notification types

Revision ID: notify_0005
Revises: notify_0004
Create Date: 2026-10-09 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notify_0005"
down_revision: str | Sequence[str] | None = "notify_0004"
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
    "assessment_reminder",
)
LIBRARY_TYPES = (
    "library_item_approved",
    "library_item_changes_requested",
    "library_item_rejected",
    "library_item_unpublished",
    "library_queue_waiting",
    "library_report_filed",
    "library_reading_list_new",
)
NEW_TYPES = (*OLD_TYPES, *LIBRARY_TYPES)
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
    """Allow the seven ``library_*`` notification types."""
    _replace_type_column(NEW_TYPES)


def downgrade() -> None:
    """Forbid the types again; their rows are deleted, they cannot be kept."""
    values = ", ".join(f"'{value}'" for value in LIBRARY_TYPES)
    op.execute(f"DELETE FROM notify.notifications WHERE type IN ({values})")
    _replace_type_column(OLD_TYPES)
