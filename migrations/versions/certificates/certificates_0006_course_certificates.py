"""certificates: course certificates (settings, templates, partners, issued).

Revision ID: certificates_0006
Revises: certificates_0005
Create Date: 2026-12-01 10:00:00.000000

New tables only; one certificate per learner and course (revoked ones stay, so a
revoked learner is not re-issued automatically). Downgrade drops the tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "certificates_0006"
down_revision: str | Sequence[str] | None = "certificates_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "certificates"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    """Create the course certificate tables."""
    op.create_table(
        "course_settings",
        sa.Column("course_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),  # noqa: E501
        sa.Column("passing_pct", sa.Integer(), server_default=sa.text("60"), nullable=False),  # noqa: E501
        sa.Column("optional_section_ids", pg.JSONB(), server_default=sa.text("'[]'"), nullable=False),  # noqa: E501
        sa.Column("tiers", pg.JSONB(), nullable=False),
        sa.Column("template_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("partner_ids", pg.JSONB(), server_default=sa.text("'[]'"), nullable=False),  # noqa: E501
        *_stamps(),
        sa.CheckConstraint("passing_pct BETWEEN 0 AND 100", name="ck_course_settings_passing"),  # noqa: E501
        schema=S,
    )
    op.create_table(
        "course_templates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("course_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("background_file_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("fields", pg.JSONB(), nullable=False),
        sa.Column("qr", pg.JSONB(), nullable=False),
        *_stamps(),
        schema=S,
    )
    op.create_index("ix_certificates_course_templates_course_id", "course_templates", ["course_id"], schema=S)  # noqa: E501
    op.create_table(
        "course_partners",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("course_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("logo_file_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("co_issued", sa.Boolean(), server_default=sa.text("true"), nullable=False),  # noqa: E501
        *_stamps(),
        schema=S,
    )
    op.create_index("ix_certificates_course_partners_course_id", "course_partners", ["course_id"], schema=S)  # noqa: E501
    op.create_table(
        "issued_course_certificates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False, unique=True),
        sa.Column("course_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("tier_key", sa.String(24), nullable=False),
        sa.Column("tier_label", pg.JSONB(), nullable=False),
        sa.Column("holder_name", sa.String(240), nullable=False),
        sa.Column("course_title", sa.String(300), nullable=False),
        sa.Column("partner", pg.JSONB(), nullable=True),
        sa.Column("template", pg.JSONB(), nullable=True),
        sa.Column("score_pct", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("course_id", "user_id", name="uq_issued_course_user"),
        schema=S,
    )
    op.create_index("ix_certificates_issued_course_certificates_course_id", "issued_course_certificates", ["course_id"], schema=S)  # noqa: E501
    op.create_index("ix_certificates_issued_course_certificates_user_id", "issued_course_certificates", ["user_id"], schema=S)  # noqa: E501


def downgrade() -> None:
    """Drop the course certificate tables."""
    op.drop_table("issued_course_certificates", schema=S)
    op.drop_table("course_partners", schema=S)
    op.drop_table("course_templates", schema=S)
    op.drop_table("course_settings", schema=S)
