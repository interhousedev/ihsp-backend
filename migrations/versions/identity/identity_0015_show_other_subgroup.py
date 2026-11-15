"""The calendar hides other subgroup lessons by default.

The web flag `timetable:hide-other-subgroup` (in `preferences.onboarding_dismissed`)
is replaced by the opposite `timetable:show-other-subgroup`; absent means hidden.
Users who had stored the old hide flag keep hiding: the flag is removed, which is
the new default. Nobody else gets a value, so they hide too.

Revision ID: identity_0015
Revises: identity_0014
Create Date: 2026-11-15 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0015"
down_revision: str | Sequence[str] | None = "identity_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HIDE = "timetable:hide-other-subgroup"
_SHOW = "timetable:show-other-subgroup"


def _replace(old: str, new: str | None) -> None:
    """Swap `old` for `new` (or drop it) in every stored `onboarding_dismissed` list."""
    added = f"|| jsonb_build_array('{new}')" if new is not None else "|| '[]'::jsonb"
    op.execute(f"""
        UPDATE id.users
        SET preferences = jsonb_set(
            preferences,
            '{{onboarding_dismissed}}',
            (
                SELECT coalesce(jsonb_agg(item), '[]'::jsonb)
                FROM jsonb_array_elements(preferences -> 'onboarding_dismissed') AS item
                WHERE item <> to_jsonb('{old}'::text)
            ) {added}
        )
        WHERE jsonb_typeof(preferences -> 'onboarding_dismissed') = 'array'
          AND (preferences -> 'onboarding_dismissed') @> jsonb_build_array('{old}')
        """)  # noqa: S608  # nosec B608 - module constants, no user input


def upgrade() -> None:
    """Drop the old hide flag: hidden is the default now."""
    _replace(_HIDE, None)
    # Users who showed everything had no flag; they now see the default (hidden).


def downgrade() -> None:
    """Back to the old flag: users that chose to show get no flag (old default = shown)."""
    _replace(_SHOW, None)
