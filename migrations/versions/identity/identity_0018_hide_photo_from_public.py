"""Rename the photo preference: hidden from the public, not only from classmates.

Revision ID: identity_0018
Revises: identity_0017
Create Date: 2026-11-28 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0018"
down_revision: str | Sequence[str] | None = "identity_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Copy `hide_photo_from_classmates` to `hide_photo_from_public`."""
    op.execute(sa.text("""
            UPDATE id.users
            SET preferences = (preferences - 'hide_photo_from_classmates')
                || jsonb_build_object(
                    'hide_photo_from_public',
                    preferences -> 'hide_photo_from_classmates'
                )
            WHERE preferences -> 'hide_photo_from_classmates' IS NOT NULL
            """))


def downgrade() -> None:
    """Copy the value back to the old key."""
    op.execute(sa.text("""
            UPDATE id.users
            SET preferences = (preferences - 'hide_photo_from_public')
                || jsonb_build_object(
                    'hide_photo_from_classmates',
                    preferences -> 'hide_photo_from_public'
                )
            WHERE preferences -> 'hide_photo_from_public' IS NOT NULL
            """))
