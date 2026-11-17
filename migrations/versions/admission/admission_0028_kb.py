"""admission FAQ knowledge base; the old assistant threads move to AI chats.

Revision ID: admission_0028_kb
Revises: admission_0027_uni_chat
Create Date: 2026-12-10 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from uuid_utils.compat import uuid7

# revision identifiers, used by Alembic.
revision: str = "admission_0028_kb"
down_revision: str | Sequence[str] | None = "admission_0027_uni_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
KB_SEARCH_SQL = "to_tsvector('simple'::regconfig, (title || ' '::text) || body)"

# (tags, {locale: (title, body)})
SEED: list[tuple[list[str], dict[str, tuple[str, str]]]] = [
    (
        ["deadlines", "early"],
        {
            "en": (
                "Early Action, Early Decision, REA and SCEA",
                "**Early Action (EA)**: apply early (usually 1 or 15 November), "
                "get an answer in December, not binding.\n\n"
                "**Early Decision (ED)**: binding. If admitted you must enroll and "
                "withdraw other applications. Apply ED to one school only.\n\n"
                "**Restrictive Early Action (REA)** and **Single-Choice Early Action "
                "(SCEA)**: not binding, but you may not apply early to most other "
                "private universities.\n\n"
                "Check each university's own rules; ED makes sense only when the "
                "family accepts the aid offer in advance.",
            ),
            "ru": (
                "Early Action, Early Decision, REA и SCEA",
                "**Early Action (EA)**: ранняя подача (обычно 1 или 15 ноября), "
                "ответ в декабре, ни к чему не обязывает.\n\n"
                "**Early Decision (ED)**: обязывающий вариант. При зачислении нужно "
                "поступить и отозвать остальные заявки. ED подают только в один "
                "университет.\n\n"
                "**Restrictive Early Action (REA)** и **Single-Choice Early Action "
                "(SCEA)**: не обязывают, но запрещают раннюю подачу в большинство "
                "других частных университетов.\n\n"
                "Проверяйте правила каждого университета; ED имеет смысл, только "
                "если семья заранее согласна с предложением о финансовой помощи.",
            ),
            "uz": (
                "Early Action, Early Decision, REA va SCEA",
                "**Early Action (EA)**: erta topshirish (odatda 1 yoki 15-noyabr), "
                "javob dekabrda, majburiyat yoʼq.\n\n"
                "**Early Decision (ED)**: majburiy. Qabul qilinsangiz, oʼqishga "
                "kirishingiz va boshqa arizalarni qaytarib olishingiz kerak. ED "
                "faqat bitta universitetga topshiriladi.\n\n"
                "**Restrictive Early Action (REA)** va **Single-Choice Early Action "
                "(SCEA)**: majburiy emas, lekin boshqa xususiy universitetlarning "
                "koʼpiga erta topshirib boʼlmaydi.\n\n"
                "Har bir universitet qoidalarini tekshiring; ED faqat oila moliyaviy "
                "yordam taklifiga oldindan rozi boʼlsa maʼqul.",
            ),
        },
    ),
    (
        ["tests", "sat", "ielts"],
        {
            "en": (
                "Test-optional admissions",
                "Test-optional means you may apply without SAT or ACT scores. "
                "Send a score when it is at or above the university's middle 50% "
                "range; otherwise leave it out. Test-optional is not test-blind: "
                "a strong score still helps. English tests (IELTS, TOEFL, Duolingo) "
                "are usually still required for international applicants.",
            ),
            "ru": (
                "Поступление без обязательных тестов (test-optional)",
                "Test-optional означает, что можно подать заявку без SAT или ACT. "
                "Отправляйте балл, если он не ниже средних 50% поступивших в этот "
                "университет; иначе не отправляйте. Test-optional не равно "
                "test-blind: сильный балл всё равно помогает. Тесты по английскому "
                "(IELTS, TOEFL, Duolingo) для иностранцев обычно обязательны.",
            ),
            "uz": (
                "Testsiz qabul (test-optional)",
                "Test-optional SAT yoki ACT natijasisiz ariza topshirish mumkinligini "
                "bildiradi. Natijangiz universitetning oʼrta 50% oraligʼidan past "
                "boʼlmasa, yuboring; aks holda yubormang. Test-optional test-blind "
                "emas: yuqori ball baribir yordam beradi. Chet elliklar uchun ingliz "
                "tili testlari (IELTS, TOEFL, Duolingo) odatda majburiy.",
            ),
        },
    ),
    (
        ["costs", "financial aid", "scholarships"],
        {
            "en": (
                "Costs and financial aid",
                "The cost of attendance includes tuition, housing, food, insurance, "
                "books and travel. Need-based aid depends on your family's income "
                "(CSS Profile or the university's own form); merit aid rewards "
                "achievements. Some universities are need-blind for international "
                "students and meet full need; most are need-aware. Use each "
                "university's net price calculator and apply for aid at the same "
                "time as for admission.",
            ),
            "ru": (
                "Стоимость обучения и финансовая помощь",
                "Полная стоимость включает обучение, жильё, питание, страховку, "
                "книги и перелёты. Помощь по нуждаемости зависит от дохода семьи "
                "(CSS Profile или форма университета); merit-стипендии дают за "
                "достижения. Некоторые университеты принимают иностранцев "
                "need-blind и покрывают всю нужду; большинство учитывают запрос "
                "помощи (need-aware). Используйте калькулятор net price каждого "
                "университета и подавайте на помощь одновременно с заявкой.",
            ),
            "uz": (
                "Oʼqish narxi va moliyaviy yordam",
                "Umumiy narx oʼqish, yotoqxona, ovqat, sugʼurta, kitoblar va "
                "yoʼl xarajatlarini oʼz ichiga oladi. Ehtiyojga asoslangan yordam "
                "oila daromadiga bogʼliq (CSS Profile yoki universitet shakli); "
                "merit stipendiyalar yutuqlar uchun beriladi. Baʼzi universitetlar "
                "chet elliklarni need-blind qabul qiladi va toʼliq ehtiyojni "
                "qoplaydi; koʼpchiligi need-aware. Har bir universitetning net price "
                "kalkulyatoridan foydalaning va yordamga ariza bilan birga topshiring.",
            ),
        },
    ),
    (
        ["transcript", "documents", "lyceum"],
        {
            "en": (
                "Getting your transcript from the lyceum",
                "1. Check that your grades for every year are complete in the app.\n"
                "2. Ask your counselor for an official transcript at least three "
                "weeks before the first deadline.\n"
                "3. The lyceum prepares the transcript in English with the grading "
                "scale, signed and stamped.\n"
                "4. Your counselor uploads it to the Common App or sends it to each "
                "university together with the school report.\n"
                "5. Mid-year and final reports follow in February and June.",
            ),
            "ru": (
                "Как получить транскрипт в лицее",
                "1. Проверьте, что оценки за все годы заполнены в приложении.\n"
                "2. Запросите официальный транскрипт у консультанта минимум за три "
                "недели до первого дедлайна.\n"
                "3. Лицей готовит транскрипт на английском со шкалой оценок, с "
                "подписью и печатью.\n"
                "4. Консультант загружает его в Common App или отправляет в каждый "
                "университет вместе с school report.\n"
                "5. Промежуточный и итоговый отчёты отправляются в феврале и июне.",
            ),
            "uz": (
                "Litseydan transkript olish",
                "1. Ilovada barcha yillar baholari toʼliq ekanini tekshiring.\n"
                "2. Birinchi muddatdan kamida uch hafta oldin maslahatchidan rasmiy "
                "transkript soʼrang.\n"
                "3. Litsey transkriptni ingliz tilida, baholash shkalasi bilan, "
                "imzo va muhr bilan tayyorlaydi.\n"
                "4. Maslahatchi uni Common App ga yuklaydi yoki har bir "
                "universitetga school report bilan birga yuboradi.\n"
                "5. Oraliq va yakuniy hisobotlar fevral va iyunda yuboriladi.",
            ),
        },
    ),
    (
        ["recommendations", "letters", "teachers"],
        {
            "en": (
                "Recommendation letters",
                "Most universities ask for one counselor letter and two teacher "
                "letters, ideally from core subjects you took in the last two years. "
                "Ask teachers in person at least a month before the deadline, then "
                "send a short brag sheet: your goals, projects and moments from "
                "their class. Invite them in the Common App and thank them "
                "afterwards. Letters in Uzbek or Russian need a certified "
                "translation.",
            ),
            "ru": (
                "Рекомендательные письма",
                "Большинство университетов просят одно письмо консультанта и два "
                "письма учителей, лучше по основным предметам последних двух лет. "
                "Попросите учителя лично минимум за месяц до дедлайна, затем "
                "отправьте краткую справку о себе: цели, проекты, эпизоды с его "
                "уроков. Пригласите учителя в Common App и поблагодарите после. "
                "Письма на узбекском или русском нужно заверенно перевести.",
            ),
            "uz": (
                "Tavsiya xatlari",
                "Koʼp universitetlar bitta maslahatchi xati va ikkita oʼqituvchi "
                "xatini soʼraydi, yaxshisi oxirgi ikki yildagi asosiy fanlardan. "
                "Oʼqituvchidan muddatdan kamida bir oy oldin shaxsan soʼrang, "
                "keyin oʼzingiz haqingizda qisqa maʼlumot yuboring: maqsadlar, "
                "loyihalar, darslaridagi lahzalar. Uni Common App ga taklif qiling "
                "va keyin minnatdorchilik bildiring. Oʼzbek yoki rus tilidagi "
                "xatlar tasdiqlangan tarjimani talab qiladi.",
            ),
        },
    ),
]


def _ts(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _json(name: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )


def upgrade() -> None:
    """Create and seed the FAQ; drop the old assistant threads."""
    table = op.create_table(
        "kb_articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(length=2), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        _json("tags"),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed(KB_SEARCH_SQL, persisted=True),
            nullable=False,
        ),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "status IN ('draft', 'published')", name=op.f("ck_kb_articles_status")
        ),
        sa.CheckConstraint(
            "locale IN ('uz', 'ru', 'en')", name=op.f("ck_kb_articles_locale")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_articles")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_kb_articles_status"), "kb_articles", ["status"], schema=S
    )
    op.create_index(
        "ix_admission_kb_articles_search",
        "kb_articles",
        ["search"],
        postgresql_using="gin",
        schema=S,
    )
    assert table is not None
    op.bulk_insert(
        table,
        [
            {
                "id": uuid7(),
                "title": title,
                "body": body,
                "locale": locale,
                "status": "published",
                "tags": tags,
            }
            for tags, texts in SEED
            for locale, (title, body) in texts.items()
        ],
    )
    op.drop_table("assistant_messages", schema=S)
    op.drop_table("assistant_threads", schema=S)


def downgrade() -> None:
    """Drop the FAQ; recreate the empty assistant tables."""
    op.create_table(
        "assistant_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        _ts("updated_at"),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_threads")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_assistant_threads_student_id"),
        "assistant_threads",
        ["student_id"],
        schema=S,
    )
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=9), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        _json("citations"),
        _json("actions"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name=op.f("ck_assistant_messages_role")
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["admission.assistant_threads.id"],
            name=op.f("fk_assistant_messages_thread_id_assistant_threads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_messages")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_assistant_messages_thread_id"),
        "assistant_messages",
        ["thread_id"],
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_assistant_messages_student_id"),
        "assistant_messages",
        ["student_id"],
        schema=S,
    )
    op.drop_table("kb_articles", schema=S)
