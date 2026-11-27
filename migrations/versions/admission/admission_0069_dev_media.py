"""admission media URLs: also accept the local development storage.

The mirror stores logos and covers under `<public endpoint>/<bucket>/`; the dev
S3 serves plain http on localhost, which the https-only checks rejected. Other
http addresses stay rejected.

Revision ID: admission_0069_dev_media
Revises: admission_0068_trajectories
Create Date: 2026-11-27 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0069_dev_media"
down_revision: str | Sequence[str] | None = "admission_0068_trajectories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
LOCAL = "http://localhost:%"


def _replace(name: str, table: str, condition: str) -> None:
    op.drop_constraint(op.f(name), table, schema=S)
    op.create_check_constraint(op.f(name), table, condition, schema=S)


def upgrade() -> None:
    """Allow `http://localhost:` media URLs besides https."""
    _replace(
        "ck_institutions_media_https",
        "institutions",
        f"(logo_url IS NULL OR logo_url LIKE 'https://%' OR logo_url LIKE '{LOCAL}')"
        " AND (cover_url IS NULL OR cover_url LIKE 'https://%'"
        f" OR cover_url LIKE '{LOCAL}')",
    )
    _replace(
        "ck_orgs_logo_https",
        "orgs",
        f"logo_url IS NULL OR logo_url LIKE 'https://%' OR logo_url LIKE '{LOCAL}'",
    )


def downgrade() -> None:
    """Back to https only (fails while local URLs are stored)."""
    _replace(
        "ck_institutions_media_https",
        "institutions",
        "(logo_url IS NULL OR logo_url LIKE 'https://%')"
        " AND (cover_url IS NULL OR cover_url LIKE 'https://%')",
    )
    _replace("ck_orgs_logo_https", "orgs", "logo_url IS NULL OR logo_url LIKE 'https://%'")
