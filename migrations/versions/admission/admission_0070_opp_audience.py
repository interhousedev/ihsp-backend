"""One opportunities catalog: each entry names the surfaces that show it.

`audience` lists `admission` and/or `my_iht`. Every existing published entry
(only approved ones live in this table; pending and rejected proposals stay in
`opportunity_submissions`) is shown on both surfaces; new rows default to
admission only until a staff member widens the audience.

Revision ID: admission_0070_opp_audience
Revises: admission_0069_dev_media
Create Date: 2026-11-27 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0070_opp_audience"
down_revision: str | Sequence[str] | None = "admission_0069_dev_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Add the audience and show every existing entry on both surfaces."""
    op.add_column(
        "opportunities",
        sa.Column(
            "audience",
            postgresql.JSONB(),
            server_default=sa.text("'[\"admission\"]'::jsonb"),
            nullable=False,
        ),
        schema=S,
    )
    op.execute(
        f'UPDATE {S}.opportunities SET audience = \'["admission","my_iht"]\'::jsonb'
    )


def downgrade() -> None:
    """Drop the audience."""
    op.drop_column("opportunities", "audience", schema=S)
