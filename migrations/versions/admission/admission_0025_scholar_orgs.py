"""admission organizations, scholarships and opportunity comments.

Adds the opportunity kind `scholarship`, the tables `orgs`,
`opportunity_comments` and `opportunity_comment_reports`, and seeds a few
organizations, scholarships and free courses (each with its `source_url`).

Revision ID: admission_0025_scholar_orgs
Revises: admission_0024_outcomes
Create Date: 2026-11-22 10:00:00.000000
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0025_scholar_orgs"
down_revision: str | Sequence[str] | None = "admission_0024_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
_JSON = postgresql.JSONB(astext_type=sa.Text())
_OLD = "kind IN ('exam', 'certification', 'course', 'event', 'recurring', 'program')"
_NEW = (
    "kind IN ('exam', 'certification', 'course', 'event', 'recurring', 'program',"
    " 'scholarship')"
)
_NS = UUID("6f0f0a52-5d5e-4d0b-9a55-1d0c5a3e0025")
_SYSTEM = UUID(int=0)


def _id(name: str) -> UUID:
    return uuid5(_NS, name)


_ORGS: list[dict[str, Any]] = [
    {
        "name": "Anthropic",
        "kind": "company",
        "website": "https://www.anthropic.com",
        "country": "USA",
    },
    {
        "name": "El-yurt umidi Foundation",
        "kind": "foundation",
        "website": "https://el-yurt.uz",
        "country": "Uzbekistan",
    },
    {
        "name": "Arizona State University",
        "kind": "university",
        "website": "https://www.asu.edu",
        "country": "USA",
    },
    {
        "name": "Harvard University",
        "kind": "university",
        "website": "https://www.harvard.edu",
        "country": "USA",
    },
]

_BASE: dict[str, Any] = {
    "summary": None,
    "url": None,
    "provider": None,
    "subject_ids": [],
    "grades": [],
    "registration_deadlines": [],
    "exam_dates": [],
    "last_year_dates": [],
    "recurrence": None,
    "lms_course_id": None,
    "country": None,
    "location": None,
    "online": False,
    "acceptance_rate": None,
    "tuition_usd": None,
    "logo_url": None,
    "host_institution": None,
    "duration_weeks": None,
    "ranking": None,
    "award_type": None,
    "coverage": [],
    "scope": None,
    "amount_text": None,
    "amount_value": None,
    "currency": None,
    "essay_required": False,
    "eligibility": None,
    "source_url": None,
    "college_credit": None,
    "credit_note": None,
    "materials": [],
}


def _opps() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "kind": "scholarship",
            "title": "Anthropic Fellows Program",
            "org": "Anthropic",
            "summary": (
                "A four-month, funded research fellowship in AI safety with "
                "mentorship from Anthropic researchers. Rolling applications."
            ),
            "url": "https://job-boards.greenhouse.io/anthropic/jobs/5183044008",
            "source_url": (
                "https://alignment.anthropic.com/2025/anthropic-fellows-program-2026"
            ),
            "award_type": "fellowship",
            "scope": "international",
            "coverage": ["stipend"],
            "amount_text": "Weekly stipend and about $15,000 a month for compute",
            "eligibility": "No PhD required; strong technical background expected.",
            "duration_weeks": 16,
            "online": True,
        },
        {
            "kind": "scholarship",
            "title": "El-yurt umidi Foundation: study abroad",
            "org": "El-yurt umidi Foundation",
            "summary": (
                "State foundation that funds bachelor's, master's and doctoral "
                "study at foreign universities for citizens of Uzbekistan."
            ),
            "url": "https://el-yurt.uz/",
            "source_url": "https://isft.uz/en/news/265",
            "award_type": "scholarship",
            "scope": "local",
            "coverage": ["full_tuition", "stipend"],
            "eligibility": (
                "2026 round: 500 quotas (167 bachelor, 232 master, 38 doctoral, "
                "63 by presidential directive); documents were accepted on "
                "April 3-24 at https://eyuf.uz."
            ),
            "country": "Uzbekistan",
        },
        {
            "kind": "course",
            "title": "ASU Universal Learner Courses",
            "org": "Arizona State University",
            "summary": (
                "Self-paced online ASU courses open to anyone; you pay only if "
                "you want the college credit."
            ),
            "url": "https://ulc.asu.edu/",
            "source_url": "https://ulc.asu.edu/how-to-enroll/pricing",
            "provider": "Arizona State University",
            "online": True,
            "college_credit": "yes",
            "credit_note": (
                "$25 enrollment fee; real ASU credit costs a $400 conversion fee."
            ),
        },
        {
            "kind": "course",
            "title": "CS50x: Introduction to Computer Science",
            "org": "Harvard University",
            "summary": "Harvard's free introductory computer science course.",
            "url": "https://cs50.harvard.edu/x",
            "source_url": "https://cs50.harvard.edu/x",
            "provider": "Harvard University",
            "online": True,
            "college_credit": "none",
            "credit_note": "Free to take; a verified certificate is paid.",
        },
    ]
    return rows


def upgrade() -> None:
    """Create the tables, allow `scholarship`, seed the catalog."""
    _create_tables()
    op.drop_constraint("ck_opportunities_kind", "opportunities", schema=S)
    op.create_check_constraint(
        op.f("ck_opportunities_kind"), "opportunities", _NEW, schema=S
    )
    _seed()


def _stamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
    ]


def _create_tables() -> None:
    updated = sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    op.create_table(
        "orgs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("logo_url", sa.String(2000), nullable=True),
        sa.Column("logo_zoom", sa.Float(), server_default=sa.text("1"), nullable=False),
        sa.Column("website", sa.String(2000), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        *_stamps(),
        updated,
        sa.CheckConstraint(
            "kind IN ('university', 'company', 'foundation', 'government', 'ngo')",
            name=op.f("ck_orgs_kind"),
        ),
        sa.CheckConstraint(
            "logo_url IS NULL OR logo_url LIKE 'https://%'",
            name=op.f("ck_orgs_logo_https"),
        ),
        sa.CheckConstraint(
            "website IS NULL OR website LIKE 'https://%'",
            name=op.f("ck_orgs_website_https"),
        ),
        sa.CheckConstraint(
            "logo_zoom BETWEEN 0.5 AND 3", name=op.f("ck_orgs_logo_zoom_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orgs")),
        schema=S,
    )
    op.create_table(
        "opportunity_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(10),
            server_default=sa.text("'published'"),
            nullable=False,
        ),
        sa.Column("hidden_by", sa.Uuid(), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('published', 'hidden', 'deleted')",
            name=op.f("ck_opportunity_comments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            [f"{S}.opportunities.id"],
            name=op.f("fk_opportunity_comments_opportunity_id_opportunities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunity_comments")),
        schema=S,
    )
    op.create_index(
        "ix_opportunity_comments_opp",
        "opportunity_comments",
        ["opportunity_id", "created_at"],
        schema=S,
    )
    op.create_table(
        "opportunity_comment_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("comment_id", sa.Uuid(), nullable=False),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column(
            "status", sa.String(10), server_default=sa.text("'open'"), nullable=False
        ),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name=op.f("ck_opportunity_comment_reports_status"),
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            [f"{S}.opportunity_comments.id"],
            name=op.f("fk_opportunity_comment_reports_comment_id_opportunity_comments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunity_comment_reports")),
        sa.UniqueConstraint(
            "comment_id",
            "reporter_id",
            name=op.f("uq_opportunity_comment_reports_comment_id"),
        ),
        schema=S,
    )
    op.create_index(
        "ix_opp_comment_reports_status",
        "opportunity_comment_reports",
        ["status", "created_at"],
        schema=S,
    )


def _seed() -> None:
    orgs = sa.table(
        "orgs",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("website", sa.String()),
        sa.column("country", sa.String()),
        schema=S,
    )
    op.bulk_insert(orgs, [{"id": _id(o["name"]), **o} for o in _ORGS])
    opps = sa.table(
        "opportunities",
        sa.column("id", sa.Uuid()),
        sa.column("kind", sa.String()),
        sa.column("title", sa.String()),
        sa.column("payload", _JSON),
        sa.column("created_by", sa.Uuid()),
        schema=S,
    )
    rows = []
    for o in _opps():
        payload = {**_BASE, **{k: v for k, v in o.items() if k != "org"}}
        payload["org_id"] = str(_id(o["org"]))
        rows.append(
            {
                "id": _id("opp:" + o["title"]),
                "kind": o["kind"],
                "title": o["title"],
                "payload": payload,
                "created_by": _SYSTEM,
            }
        )
    op.bulk_insert(opps, rows)


def downgrade() -> None:
    """Drop the tables, the seeds and the kind."""
    op.drop_index(
        "ix_opp_comment_reports_status",
        table_name="opportunity_comment_reports",
        schema=S,
    )
    op.drop_table("opportunity_comment_reports", schema=S)
    op.drop_index(
        "ix_opportunity_comments_opp", table_name="opportunity_comments", schema=S
    )
    op.drop_table("opportunity_comments", schema=S)
    op.drop_table("orgs", schema=S)
    op.execute(
        f"DELETE FROM {S}.opportunities WHERE kind = 'scholarship'"
        f" OR created_by = '{_SYSTEM}'"
    )
    op.drop_constraint("ck_opportunities_kind", "opportunities", schema=S)
    op.create_check_constraint(
        op.f("ck_opportunities_kind"), "opportunities", _OLD, schema=S
    )
