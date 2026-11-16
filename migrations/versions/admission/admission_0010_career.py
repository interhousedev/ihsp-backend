"""admission career: inventory questions, majors taxonomy, career plans.

Revision ID: admission_0010
Revises: admission_0006
Create Date: 2026-11-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from uuid_utils.compat import uuid7

# revision identifiers, used by Alembic.
revision: str = "admission_0010"
down_revision: str | Sequence[str] | None = "admission_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = postgresql.JSONB(astext_type=sa.Text())

# Starter inventory; administrators edit or replace it on the career admin page.
QUESTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "interests",
        "Which school subjects make you lose track of time?",
        "На каких предметах вы забываете о времени?",
        "Qaysi fanlarda vaqt qanday oʼtganini sezmay qolasiz?",
    ),
    (
        "interests",
        "What do you read, watch or build in your free time?",
        "Что вы читаете, смотрите или создаёте в свободное время?",
        "Boʼsh vaqtingizda nimani oʼqiysiz, koʼrasiz yoki yaratasiz?",
    ),
    (
        "interests",
        "Which problem in your city or the world would you like to solve?",
        "Какую проблему вашего города или мира вы хотели бы решить?",
        "Shahringiz yoki dunyodagi qaysi muammoni hal qilishni istardingiz?",
    ),
    (
        "interests",
        "Do you prefer working with people, ideas, data or things? Why?",
        "Вам ближе работа с людьми, идеями, данными или вещами? Почему?",
        "Odamlar, gʼoyalar, maʼlumotlar yoki narsalar bilan ishlash sizga "
        "yaqinmi? Nega?",
    ),
    (
        "values",
        "What matters most to you in future work: money, impact, freedom, "
        "stability or something else?",
        "Что для вас важнее всего в будущей работе: доход, польза, свобода, "
        "стабильность или что-то другое?",
        "Kelajakdagi ishda siz uchun eng muhimi nima: daromad, foyda, erkinlik, "
        "barqarorlik yoki boshqa narsa?",
    ),
    (
        "values",
        "Describe a moment when you felt proud of yourself.",
        "Опишите момент, когда вы гордились собой.",
        "Oʼzingiz bilan faxrlangan bir lahzani tasvirlab bering.",
    ),
    (
        "values",
        "Who do you admire, and what do they do?",
        "Кем вы восхищаетесь и чем занимается этот человек?",
        "Kimga havas qilasiz va u nima bilan shugʼullanadi?",
    ),
    (
        "values",
        "Where would you like to live and work in ten years?",
        "Где вы хотели бы жить и работать через десять лет?",
        "Oʼn yildan keyin qayerda yashab, ishlashni istardingiz?",
    ),
    (
        "skills",
        "What do friends or teachers ask you to help with?",
        "С чем вас просят помочь друзья или учителя?",
        "Doʼstlaringiz yoki oʼqituvchilaringiz sizdan nimada yordam soʼraydi?",
    ),
    (
        "skills",
        "Which skill have you improved the most in the last year, and how?",
        "Какой навык вы сильнее всего развили за последний год и как?",
        "Oʼtgan yil qaysi koʼnikmangizni eng koʼp rivojlantirdingiz va qanday?",
    ),
    (
        "skills",
        "Tell about something you made or led from start to finish.",
        "Расскажите о том, что вы сделали или возглавили от начала до конца.",
        "Boshidan oxirigacha oʼzingiz yaratgan yoki boshqargan ishingiz haqida "
        "aytib bering.",
    ),
    (
        "skills",
        "Which skill would you most like to learn next?",
        "Какому навыку вы больше всего хотели бы научиться?",
        "Keyingi navbatda qaysi koʼnikmani oʼrganishni eng koʼp istaysiz?",
    ),
)

# Starter taxonomy: (code, area, en, ru, uz, minor_ok).
MAJORS: tuple[tuple[str, str, str, str, str, bool], ...] = (
    (
        "computer_science",
        "STEM",
        "Computer Science",
        "Информатика",
        "Informatika",
        True,
    ),
    (
        "data_science",
        "STEM",
        "Data Science",
        "Науки о данных",
        "Maʼlumotlar fani",
        True,
    ),
    ("mathematics", "STEM", "Mathematics", "Математика", "Matematika", True),
    ("physics", "STEM", "Physics", "Физика", "Fizika", True),
    ("chemistry", "STEM", "Chemistry", "Химия", "Kimyo", True),
    ("biology", "STEM", "Biology", "Биология", "Biologiya", True),
    (
        "mechanical_engineering",
        "Engineering",
        "Mechanical Engineering",
        "Машиностроение",
        "Mashinasozlik",
        False,
    ),
    (
        "electrical_engineering",
        "Engineering",
        "Electrical Engineering",
        "Электротехника",
        "Elektrotexnika",
        False,
    ),
    (
        "civil_engineering",
        "Engineering",
        "Civil Engineering",
        "Гражданское строительство",
        "Qurilish muhandisligi",
        False,
    ),
    ("medicine", "Health", "Pre-medicine", "Медицина", "Tibbiyot", False),
    (
        "public_health",
        "Health",
        "Public Health",
        "Общественное здоровье",
        "Jamoat salomatligi",
        True,
    ),
    ("economics", "Business", "Economics", "Экономика", "Iqtisodiyot", True),
    (
        "business",
        "Business",
        "Business Administration",
        "Управление бизнесом",
        "Biznes boshqaruvi",
        True,
    ),
    ("finance", "Business", "Finance", "Финансы", "Moliya", True),
    (
        "international_relations",
        "Social sciences",
        "International Relations",
        "Международные отношения",
        "Xalqaro munosabatlar",
        True,
    ),
    ("psychology", "Social sciences", "Psychology", "Психология", "Psixologiya", True),
    ("law", "Social sciences", "Law", "Право", "Huquqshunoslik", False),
    (
        "political_science",
        "Social sciences",
        "Political Science",
        "Политология",
        "Siyosatshunoslik",
        True,
    ),
    ("linguistics", "Humanities", "Linguistics", "Лингвистика", "Tilshunoslik", True),
    ("history", "Humanities", "History", "История", "Tarix", True),
    ("philosophy", "Humanities", "Philosophy", "Философия", "Falsafa", True),
    ("architecture", "Arts", "Architecture", "Архитектура", "Arxitektura", False),
    ("design", "Arts", "Design", "Дизайн", "Dizayn", True),
    ("music", "Arts", "Music", "Музыка", "Musiqa", True),
)


def _timestamps() -> list[sa.Column]:
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
    """Create the career tables and seed the starter inventory and taxonomy."""
    questions = op.create_table(
        "career_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=False),
        sa.Column("prompt", _JSON, nullable=False),
        sa.Column(
            "sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "section IN ('interests', 'values', 'skills')",
            name=op.f("ck_career_questions_section"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_career_questions")),
        schema="admission",
    )
    majors = op.create_table(
        "career_majors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("area", sa.String(length=48), nullable=False),
        sa.Column("name", _JSON, nullable=False),
        sa.Column(
            "minor_ok", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_career_majors")),
        sa.UniqueConstraint("code", name=op.f("uq_career_majors_code")),
        schema="admission",
    )
    op.create_table(
        "career_plans",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "answers", _JSON, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "professions", _JSON, server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "majors", _JSON, server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "minors", _JSON, server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("fit", _JSON, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("spike", _JSON, nullable=True),
        sa.Column("spike_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_career_plans")),
        schema="admission",
    )
    op.bulk_insert(
        questions,
        [
            {
                "id": uuid7(),
                "section": section,
                "prompt": {"en": en, "ru": ru, "uz": uz},
                "sort_order": index,
                "active": True,
            }
            for index, (section, en, ru, uz) in enumerate(QUESTIONS)
        ],
    )
    op.bulk_insert(
        majors,
        [
            {
                "id": uuid7(),
                "code": code,
                "area": area,
                "name": {"en": en, "ru": ru, "uz": uz},
                "minor_ok": minor_ok,
                "sort_order": index,
                "active": True,
            }
            for index, (code, area, en, ru, uz, minor_ok) in enumerate(MAJORS)
        ],
    )


def downgrade() -> None:
    """Drop the career tables."""
    op.drop_table("career_plans", schema="admission")
    op.drop_table("career_majors", schema="admission")
    op.drop_table("career_questions", schema="admission")
