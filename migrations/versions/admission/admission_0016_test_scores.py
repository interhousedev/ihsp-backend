"""admission tests & certificates: the test catalog and student entries.

Revision ID: admission_0016_test_scores
Revises: admission_0015_items_status
Create Date: 2026-11-17 12:00:00.000000
"""

from collections.abc import Sequence
from typing import Any

from app.shared.ids import new_id

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0016_test_scores"
down_revision: str | Sequence[str] | None = "admission_0015_items_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def _sec(
    key: str, names: tuple[str, str, str], lo: float, hi: float, step: float = 1
) -> dict[str, Any]:
    uz, ru, en = names
    return {
        "key": key,
        "names": {"uz": uz, "ru": ru, "en": en},
        "min": lo,
        "max": hi,
        "step": step,
        "choices": [],
    }


def _names(uz: str, ru: str, en: str) -> dict[str, str]:
    return {"uz": uz, "ru": ru, "en": en}


_TOTAL = ("Jami", "Итого", "Total")
_READING = ("Oʼqish", "Чтение", "Reading")
_LISTENING = ("Tinglash", "Аудирование", "Listening")
_WRITING = ("Yozish", "Письмо", "Writing")
_SPEAKING = ("Gapirish", "Говорение", "Speaking")


def _cambridge(key: str, uz: str, ru: str, en: str, pos: int) -> dict[str, Any]:
    return {
        "key": key,
        "names": _names(uz, ru, en),
        "sections": [
            _sec(
                "reading_use",
                (
                    "Oʼqish va til qoidalari",
                    "Чтение и грамматика",
                    "Reading and Use of English",
                ),
                80,
                230,
            ),
            _sec("writing", _WRITING, 80, 230),
            _sec("listening", _LISTENING, 80, 230),
            _sec("speaking", _SPEAKING, 80, 230),
        ],
        "total": _sec("total", ("Umumiy ball", "Общий балл", "Overall score"), 80, 230),
        "total_mode": "mean_int",
        "superscore": False,
        "needs_label": False,
        "needs_level": False,
        "position": pos,
    }


def _plain(
    key: str,
    names: dict[str, str],
    total: dict[str, Any] | None,
    pos: int,
    **flags: bool,
) -> dict[str, Any]:
    return {
        "key": key,
        "names": names,
        "sections": [],
        "total": total,
        "total_mode": "manual" if total else "none",
        "superscore": False,
        "needs_label": flags.get("label", False),
        "needs_level": flags.get("level", False),
        "position": pos,
    }


SEED: tuple[dict[str, Any], ...] = (
    {
        "key": "sat",
        "names": _names("SAT", "SAT", "SAT"),
        "sections": [
            _sec(
                "ebrw",
                (
                    "Oʼqish va yozish",
                    "Чтение и письмо",
                    "Evidence-Based Reading and Writing",
                ),
                200,
                800,
                10,
            ),
            _sec("math", ("Matematika", "Математика", "Math"), 200, 800, 10),
        ],
        "total": _sec("total", _TOTAL, 400, 1600, 10),
        "total_mode": "sum",
        "superscore": True,
        "needs_label": False,
        "needs_level": False,
        "position": 10,
    },
    {
        "key": "act",
        "names": _names("ACT", "ACT", "ACT"),
        "sections": [
            _sec("english", ("Ingliz tili", "Английский", "English"), 1, 36),
            _sec("math", ("Matematika", "Математика", "Math"), 1, 36),
            _sec("reading", _READING, 1, 36),
            _sec("science", ("Fan", "Естественные науки", "Science"), 1, 36),
        ],
        "total": _sec("composite", ("Kompozit", "Композит", "Composite"), 1, 36),
        "total_mode": "mean_int",
        "superscore": True,
        "needs_label": False,
        "needs_level": False,
        "position": 20,
    },
    {
        "key": "ielts_academic",
        "names": _names("IELTS Academic", "IELTS Academic", "IELTS Academic"),
        "sections": [
            _sec("listening", _LISTENING, 0, 9, 0.5),
            _sec("reading", _READING, 0, 9, 0.5),
            _sec("writing", _WRITING, 0, 9, 0.5),
            _sec("speaking", _SPEAKING, 0, 9, 0.5),
        ],
        "total": _sec(
            "overall", ("Umumiy band", "Общий балл", "Overall band"), 0, 9, 0.5
        ),
        "total_mode": "mean_half",
        "superscore": False,
        "needs_label": False,
        "needs_level": False,
        "position": 30,
    },
    {
        "key": "toefl_ibt",
        "names": _names("TOEFL iBT", "TOEFL iBT", "TOEFL iBT"),
        "sections": [
            _sec("reading", _READING, 0, 30),
            _sec("listening", _LISTENING, 0, 30),
            _sec("speaking", _SPEAKING, 0, 30),
            _sec("writing", _WRITING, 0, 30),
        ],
        "total": _sec("total", _TOTAL, 0, 120),
        "total_mode": "sum",
        "superscore": False,
        "needs_label": False,
        "needs_level": False,
        "position": 40,
    },
    _plain(
        "duolingo",
        _names(
            "Duolingo English Test", "Duolingo English Test", "Duolingo English Test"
        ),
        _sec("total", _TOTAL, 10, 160, 5),
        50,
    ),
    _plain(
        "ap",
        _names("AP fani", "Предмет AP", "AP subject"),
        _sec("score", ("Ball", "Балл", "Score"), 1, 5),
        60,
        label=True,
    ),
    _plain(
        "ib_diploma",
        _names("IB Diploma", "IB Diploma", "IB Diploma"),
        _sec("total", _TOTAL, 0, 45),
        70,
    ),
    _plain(
        "ib_subject",
        _names("IB fani", "Предмет IB", "IB subject"),
        _sec("score", ("Ball", "Балл", "Score"), 1, 7),
        80,
        label=True,
        level=True,
    ),
    {
        **_plain(
            "a_level",
            _names("A-Level fani", "Предмет A-Level", "A-Level subject"),
            {
                **_sec("grade", ("Baho", "Оценка", "Grade"), 0, 0),
                "choices": ["A*", "A", "B", "C", "D", "E", "U"],
            },
            90,
            label=True,
        ),
    },
    _cambridge(
        "cambridge_c1",
        "Cambridge C1 Advanced",
        "Cambridge C1 Advanced",
        "Cambridge C1 Advanced",
        100,
    ),
    _cambridge(
        "cambridge_c2",
        "Cambridge C2 Proficiency",
        "Cambridge C2 Proficiency",
        "Cambridge C2 Proficiency",
        110,
    ),
    _plain(
        "olympiad",
        _names(
            "Olimpiada yoki boshqa sertifikat",
            "Олимпиада или другой сертификат",
            "Olympiad or other certificate",
        ),
        None,
        120,
        label=True,
        level=True,
    ),
)


def _created() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _updated() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _json(name: str, default: str | None = None, null: bool = False) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(default) if default else None,
        nullable=null,
    )


def upgrade() -> None:
    """Create the tables and seed the catalog."""
    catalog = op.create_table(
        "test_catalog",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        _json("names"),
        _json("sections", "'[]'::jsonb"),
        _json("total", null=True),
        sa.Column("total_mode", sa.String(length=10), nullable=False),
        sa.Column("superscore", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("needs_label", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("needs_level", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_catalog")),
        sa.UniqueConstraint("key", name=op.f("uq_test_catalog_key")),
        schema=S,
    )
    op.create_table(
        "test_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=14), nullable=False),
        sa.Column("test_date", sa.Date(), nullable=True),
        sa.Column("registration_deadline", sa.Date(), nullable=True),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("level", sa.String(length=60), nullable=True),
        _json("sections", "'{}'::jsonb"),
        _json("total", null=True),
        sa.Column("certificate_document_id", sa.Uuid(), nullable=True),
        sa.Column("verification_url", sa.String(length=500), nullable=True),
        sa.Column("send_note", sa.String(length=500), nullable=True),
        sa.Column("is_official", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("verified_by", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        _updated(),
        sa.CheckConstraint(
            "status IN ('planned', 'registered', 'taken', 'score_received')",
            name=op.f("ck_test_scores_status"),
        ),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["admission.test_catalog.id"],
            name=op.f("fk_test_scores_test_id_test_catalog"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["certificate_document_id"],
            ["admission.documents.id"],
            name=op.f("fk_test_scores_certificate_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_scores")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_test_scores_student_id"),
        "test_scores",
        ["student_id"],
        schema=S,
    )
    op.bulk_insert(catalog, [{"id": new_id(), **row} for row in SEED])


def downgrade() -> None:
    """Drop the tables."""
    op.drop_table("test_scores", schema=S)
    op.drop_table("test_catalog", schema=S)
