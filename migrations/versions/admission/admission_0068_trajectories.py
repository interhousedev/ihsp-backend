"""Educational trajectories and student progress; seed three examples.

Revision ID: admission_0068_trajectories
Revises: admission_0067_attached_books
Create Date: 2026-11-23 12:00:00.000000
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "admission_0068_trajectories"
down_revision: str | Sequence[str] | None = "admission_0067_attached_books"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"

T3 = tuple[str, str, str]
# (id, kind, level, optional, title en/ru/uz, description en/ru/uz, prerequisites)
N = tuple[str, str, str, bool, T3, T3, tuple[str, ...]]


def _json(name: str, default: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(default),
        nullable=False,
    )


def _i18n(t: T3) -> dict[str, str]:
    return {"en": t[0], "ru": t[1], "uz": t[2]}


def _graph(stages: list[tuple[str, T3, list[N]]]) -> tuple[list[Any], list[Any]]:
    out: list[Any] = []
    edges: list[Any] = []
    for sid, title, nodes in stages:
        out.append(
            {
                "id": sid,
                "title": _i18n(title),
                "nodes": [
                    {
                        "id": nid,
                        "title": _i18n(nt),
                        "kind": kind,
                        "level": level,
                        "description": _i18n(nd),
                        "optional": optional,
                        "resources": [],
                    }
                    for nid, kind, level, optional, nt, nd, _ in nodes
                ],
            }
        )
        for nid, *_, after in nodes:
            edges += [{"before": b, "after": nid} for b in after]
    return out, edges


FOUNDATIONS: T3 = ("Foundations", "Основы", "Asoslar")
PRACTICE: T3 = ("Practice", "Практика", "Amaliyot")
APPLYING: T3 = ("Applying", "Поступление", "Hujjat topshirish")

CS = _graph(
    [
        (
            "foundations",
            FOUNDATIONS,
            [
                (
                    "math-basics",
                    "topic",
                    "beginner",
                    False,
                    (
                        "School algebra and functions",
                        "Школьная алгебра и функции",
                        "Maktab algebrasi va funksiyalar",
                    ),
                    (
                        "Equations, functions and graphs used across programming.",
                        "Уравнения, функции и графики, "
                        "которые нужны в программировании.",
                        "Dasturlashda kerak boʼladigan tenglamalar, "
                        "funksiyalar va grafiklar.",
                    ),
                    (),
                ),
                (
                    "programming-intro",
                    "course",
                    "beginner",
                    False,
                    (
                        "Introduction to programming (Python)",
                        "Введение в программирование (Python)",
                        "Dasturlashga kirish (Python)",
                    ),
                    (
                        "Variables, conditions, loops, functions and small programs.",
                        "Переменные, условия, циклы, функции и небольшие программы.",
                        "Oʼzgaruvchilar, shartlar, sikllar, "
                        "funksiyalar va kichik dasturlar.",
                    ),
                    (),
                ),
                (
                    "english-tech",
                    "topic",
                    "beginner",
                    True,
                    (
                        "Technical English",
                        "Технический английский",
                        "Texnik ingliz tili",
                    ),
                    (
                        "Read documentation and error messages in English.",
                        "Читать документацию и сообщения об ошибках на английском.",
                        "Hujjatlar va xato xabarlarini ingliz tilida oʼqish.",
                    ),
                    (),
                ),
            ],
        ),
        (
            "core",
            ("Core knowledge", "Ядро знаний", "Asosiy bilimlar"),
            [
                (
                    "data-structures",
                    "topic",
                    "intermediate",
                    False,
                    (
                        "Data structures and algorithms",
                        "Структуры данных и алгоритмы",
                        "Maʼlumotlar tuzilmalari va algoritmlar",
                    ),
                    (
                        "Arrays, lists, trees, sorting, searching and complexity.",
                        "Массивы, списки, деревья, сортировка, поиск и сложность.",
                        "Massivlar, roʼyxatlar, daraxtlar, "
                        "saralash, qidirish va murakkablik.",
                    ),
                    ("programming-intro", "math-basics"),
                ),
                (
                    "discrete-math",
                    "topic",
                    "intermediate",
                    False,
                    (
                        "Discrete mathematics",
                        "Дискретная математика",
                        "Diskret matematika",
                    ),
                    (
                        "Logic, sets, combinatorics and graphs.",
                        "Логика, множества, комбинаторика и графы.",
                        "Mantiq, toʼplamlar, kombinatorika va graflar.",
                    ),
                    ("math-basics",),
                ),
                (
                    "git",
                    "topic",
                    "beginner",
                    False,
                    (
                        "Version control with Git",
                        "Контроль версий с Git",
                        "Git bilan versiyalarni boshqarish",
                    ),
                    (
                        "Commits, branches and publishing code online.",
                        "Коммиты, ветки и публикация кода в интернете.",
                        "Kommitlar, tarmoqlar va kodni internetda eʼlon qilish.",
                    ),
                    ("programming-intro",),
                ),
                (
                    "web-basics",
                    "topic",
                    "beginner",
                    True,
                    (
                        "Web basics: HTML, CSS, JavaScript",
                        "Основы веба: HTML, CSS, JavaScript",
                        "Veb asoslari: HTML, CSS, JavaScript",
                    ),
                    (
                        "How web pages are built and shown in a browser.",
                        "Как устроены веб-страницы и как браузер их показывает.",
                        "Veb-sahifalar qanday tuzilgani va "
                        "brauzerda qanday koʼrsatilishi.",
                    ),
                    ("programming-intro",),
                ),
            ],
        ),
        (
            "practice",
            PRACTICE,
            [
                (
                    "own-project",
                    "project",
                    "intermediate",
                    False,
                    (
                        "Build and publish your own project",
                        "Свой проект с публикацией",
                        "Oʼz loyihangizni yaratib eʼlon qiling",
                    ),
                    (
                        "A small app or tool that solves a real problem.",
                        "Небольшое приложение или инструмент для реальной задачи.",
                        "Haqiqiy muammoni hal qiladigan kichik ilova yoki vosita.",
                    ),
                    ("data-structures", "git"),
                ),
                (
                    "contest",
                    "exam",
                    "advanced",
                    True,
                    (
                        "Programming olympiad or contest",
                        "Олимпиада или контест по программированию",
                        "Dasturlash olimpiadasi yoki musobaqasi",
                    ),
                    (
                        "Solve algorithmic problems under time limits.",
                        "Решать алгоритмические задачи на время.",
                        "Algoritmik masalalarni vaqt chegarasida yechish.",
                    ),
                    ("data-structures", "discrete-math"),
                ),
            ],
        ),
        (
            "applying",
            APPLYING,
            [
                (
                    "portfolio",
                    "milestone",
                    "intermediate",
                    False,
                    (
                        "Portfolio for university applications",
                        "Портфолио для поступления",
                        "Universitetga kirish uchun portfolio",
                    ),
                    (
                        "Describe your projects and results in the application.",
                        "Опишите свои проекты и результаты в заявке.",
                        "Arizada loyihalaringiz va natijalaringizni tasvirlang.",
                    ),
                    ("own-project",),
                ),
            ],
        ),
    ]
)

MEDICINE = _graph(
    [
        (
            "foundations",
            FOUNDATIONS,
            [
                (
                    "biology-core",
                    "topic",
                    "beginner",
                    False,
                    (
                        "Cell biology and genetics",
                        "Клеточная биология и генетика",
                        "Hujayra biologiyasi va genetika",
                    ),
                    (
                        "Cell structure, DNA, heredity and evolution.",
                        "Строение клетки, ДНК, наследственность и эволюция.",
                        "Hujayra tuzilishi, DNK, irsiyat va evolyutsiya.",
                    ),
                    (),
                ),
                (
                    "chemistry-core",
                    "topic",
                    "beginner",
                    False,
                    (
                        "General and organic chemistry",
                        "Общая и органическая химия",
                        "Umumiy va organik kimyo",
                    ),
                    (
                        "Reactions, solutions and carbon compounds.",
                        "Реакции, растворы и соединения углерода.",
                        "Reaksiyalar, eritmalar va uglerod birikmalari.",
                    ),
                    (),
                ),
                (
                    "physics-core",
                    "topic",
                    "beginner",
                    True,
                    (
                        "Physics for life sciences",
                        "Физика для естественных наук",
                        "Tabiiy fanlar uchun fizika",
                    ),
                    (
                        "Mechanics, optics and electricity in the human body.",
                        "Механика, оптика и электричество в организме человека.",
                        "Inson organizmidagi mexanika, optika va elektr.",
                    ),
                    (),
                ),
            ],
        ),
        (
            "deepening",
            ("Deepening", "Углубление", "Chuqurlashtirish"),
            [
                (
                    "anatomy",
                    "topic",
                    "intermediate",
                    False,
                    (
                        "Human anatomy and physiology",
                        "Анатомия и физиология человека",
                        "Odam anatomiyasi va fiziologiyasi",
                    ),
                    (
                        "Organ systems and how they work together.",
                        "Системы органов и их совместная работа.",
                        "Aʼzolar tizimlari va ularning birgalikdagi ishi.",
                    ),
                    ("biology-core",),
                ),
                (
                    "biochemistry",
                    "topic",
                    "intermediate",
                    False,
                    ("Biochemistry basics", "Основы биохимии", "Biokimyo asoslari"),
                    (
                        "Proteins, enzymes and metabolism.",
                        "Белки, ферменты и обмен веществ.",
                        "Oqsillar, fermentlar va moddalar almashinuvi.",
                    ),
                    ("biology-core", "chemistry-core"),
                ),
                (
                    "statistics",
                    "topic",
                    "intermediate",
                    True,
                    (
                        "Statistics for research",
                        "Статистика для исследований",
                        "Tadqiqotlar uchun statistika",
                    ),
                    (
                        "Averages, spread, samples and reading study results.",
                        "Средние, разброс, выборки и чтение результатов исследований.",
                        "Oʼrtacha qiymatlar, tarqoqlik, tanlanmalar "
                        "va tadqiqot natijalarini oʼqish.",
                    ),
                    (),
                ),
            ],
        ),
        (
            "practice",
            PRACTICE,
            [
                (
                    "first-aid",
                    "course",
                    "beginner",
                    False,
                    (
                        "First aid training",
                        "Курс первой помощи",
                        "Birinchi yordam kursi",
                    ),
                    (
                        "Basic life support and help in emergencies.",
                        "Базовая сердечно-лёгочная реанимация "
                        "и помощь в экстренных случаях.",
                        "Asosiy hayotiy yordam va favqulodda vaziyatlarda yordam.",
                    ),
                    (),
                ),
                (
                    "volunteering",
                    "project",
                    "intermediate",
                    False,
                    (
                        "Volunteering in a healthcare setting",
                        "Волонтёрство в сфере здравоохранения",
                        "Sogʼliqni saqlash sohasida volontyorlik",
                    ),
                    (
                        "Regular help at a clinic, hospital or health charity.",
                        "Регулярная помощь в клинике, больнице или медицинском фонде.",
                        "Klinika, shifoxona yoki tibbiy jamgʼarmada muntazam yordam.",
                    ),
                    ("first-aid",),
                ),
                (
                    "research",
                    "project",
                    "advanced",
                    True,
                    (
                        "School research project in biology or chemistry",
                        "Школьный исследовательский проект по биологии или химии",
                        "Biologiya yoki kimyo boʼyicha maktab tadqiqot loyihasi",
                    ),
                    (
                        "Ask a question, run an experiment, report the results.",
                        "Поставить вопрос, провести эксперимент, описать результаты.",
                        "Savol qoʼyish, tajriba oʼtkazish, natijalarni yozish.",
                    ),
                    ("biochemistry", "statistics"),
                ),
            ],
        ),
        (
            "applying",
            APPLYING,
            [
                (
                    "olympiad",
                    "exam",
                    "advanced",
                    True,
                    (
                        "Biology or chemistry olympiad",
                        "Олимпиада по биологии или химии",
                        "Biologiya yoki kimyo olimpiadasi",
                    ),
                    (
                        "Test your knowledge beyond the school programme.",
                        "Проверьте знания сверх школьной программы.",
                        "Bilimingizni maktab dasturidan tashqarida sinab koʼring.",
                    ),
                    ("anatomy",),
                ),
                (
                    "entrance-exams",
                    "milestone",
                    "advanced",
                    False,
                    (
                        "Entrance exams in biology and chemistry",
                        "Вступительные экзамены по биологии и химии",
                        "Biologiya va kimyo boʼyicha kirish imtihonlari",
                    ),
                    (
                        "Check the exams your chosen universities require.",
                        "Уточните, какие экзамены требуют выбранные университеты.",
                        "Tanlagan universitetlaringiz qaysi "
                        "imtihonlarni talab qilishini aniqlang.",
                    ),
                    ("anatomy", "biochemistry"),
                ),
            ],
        ),
    ]
)

ECONOMICS = _graph(
    [
        (
            "foundations",
            FOUNDATIONS,
            [
                (
                    "algebra-calculus",
                    "topic",
                    "beginner",
                    False,
                    (
                        "Algebra and introductory calculus",
                        "Алгебра и начала анализа",
                        "Algebra va analiz asoslari",
                    ),
                    (
                        "Functions, derivatives and optimisation.",
                        "Функции, производные и оптимизация.",
                        "Funksiyalar, hosilalar va optimallashtirish.",
                    ),
                    (),
                ),
                (
                    "micro",
                    "topic",
                    "beginner",
                    False,
                    (
                        "Microeconomics: supply, demand, markets",
                        "Микроэкономика: спрос, предложение, рынки",
                        "Mikroiqtisodiyot: talab, taklif, bozorlar",
                    ),
                    (
                        "How households and firms make choices.",
                        "Как домохозяйства и фирмы принимают решения.",
                        "Uy xoʼjaliklari va firmalar qanday qaror qabul qiladi.",
                    ),
                    (),
                ),
                (
                    "macro",
                    "topic",
                    "beginner",
                    False,
                    (
                        "Macroeconomics: GDP, inflation, unemployment",
                        "Макроэкономика: ВВП, инфляция, безработица",
                        "Makroiqtisodiyot: YaIM, inflyatsiya, ishsizlik",
                    ),
                    (
                        "How a whole economy grows and how policy affects it.",
                        "Как растёт экономика страны и как на неё влияет политика.",
                        "Butun iqtisodiyot qanday oʼsadi va "
                        "siyosat unga qanday taʼsir qiladi.",
                    ),
                    (),
                ),
            ],
        ),
        (
            "tools",
            ("Tools", "Инструменты", "Vositalar"),
            [
                (
                    "statistics",
                    "topic",
                    "intermediate",
                    False,
                    (
                        "Statistics and probability",
                        "Статистика и теория вероятностей",
                        "Statistika va ehtimollar nazariyasi",
                    ),
                    (
                        "Describe data and draw careful conclusions.",
                        "Описывать данные и делать аккуратные выводы.",
                        "Maʼlumotlarni tasvirlash va ehtiyotkor xulosalar chiqarish.",
                    ),
                    ("algebra-calculus",),
                ),
                (
                    "spreadsheets",
                    "course",
                    "beginner",
                    False,
                    (
                        "Spreadsheets for data analysis",
                        "Электронные таблицы для анализа данных",
                        "Maʼlumotlarni tahlil qilish uchun elektron jadvallar",
                    ),
                    (
                        "Formulas, charts and pivot tables.",
                        "Формулы, диаграммы и сводные таблицы.",
                        "Formulalar, diagrammalar va yigʼma jadvallar.",
                    ),
                    (),
                ),
                (
                    "personal-finance",
                    "topic",
                    "beginner",
                    True,
                    (
                        "Personal finance and accounting basics",
                        "Личные финансы и основы бухучёта",
                        "Shaxsiy moliya va buxgalteriya asoslari",
                    ),
                    (
                        "Budgets, interest, balance sheets and income statements.",
                        "Бюджет, проценты, баланс и отчёт о прибылях.",
                        "Byudjet, foizlar, balans va daromadlar hisoboti.",
                    ),
                    (),
                ),
            ],
        ),
        (
            "practice",
            PRACTICE,
            [
                (
                    "textbook",
                    "book",
                    "intermediate",
                    False,
                    (
                        "Read an introductory economics textbook",
                        "Прочитать вводный учебник по экономике",
                        "Iqtisodiyot boʼyicha kirish darsligini oʼqing",
                    ),
                    (
                        "Work through the chapters and their exercises.",
                        "Пройдите главы и упражнения к ним.",
                        "Boblar va ulardagi mashqlarni bajaring.",
                    ),
                    ("micro", "macro"),
                ),
                (
                    "data-project",
                    "project",
                    "intermediate",
                    False,
                    (
                        "Analyse public economic data",
                        "Анализ открытых экономических данных",
                        "Ochiq iqtisodiy maʼlumotlarni tahlil qilish",
                    ),
                    (
                        "Pick a question and answer it with published statistics.",
                        "Выберите вопрос и ответьте на него "
                        "по опубликованной статистике.",
                        "Savol tanlang va unga eʼlon qilingan "
                        "statistika asosida javob bering.",
                    ),
                    ("statistics", "spreadsheets", "macro"),
                ),
                (
                    "essay-contest",
                    "project",
                    "advanced",
                    True,
                    (
                        "Economics essay competition",
                        "Конкурс эссе по экономике",
                        "Iqtisodiyot boʼyicha esse tanlovi",
                    ),
                    (
                        "Argue a position on an economic question in writing.",
                        "Письменно обоснуйте позицию по экономическому вопросу.",
                        "Iqtisodiy masala boʼyicha oʼz pozitsiyangizni yozma asoslang.",
                    ),
                    ("textbook",),
                ),
            ],
        ),
        (
            "applying",
            APPLYING,
            [
                (
                    "portfolio",
                    "milestone",
                    "intermediate",
                    False,
                    (
                        "Application portfolio",
                        "Портфолио для поступления",
                        "Ariza uchun portfolio",
                    ),
                    (
                        "Show your projects, reading and results in the application.",
                        "Покажите в заявке свои проекты, прочитанное и результаты.",
                        "Arizada loyihalaringiz, oʼqiganlaringiz "
                        "va natijalaringizni koʼrsating.",
                    ),
                    ("data-project",),
                ),
            ],
        ),
    ]
)

SEED: list[tuple[str, str, str, T3, T3, tuple[list[Any], list[Any]]]] = [
    (
        "01968a00-0000-7000-8000-000000000101",
        "computer-science",
        "cs_it",
        ("Computer Science", "Информатика", "Informatika"),
        (
            "From first programs to algorithms and your own projects.",
            "От первых программ до алгоритмов и собственных проектов.",
            "Birinchi dasturlardan algoritmlar va oʼz loyihalaringizgacha.",
        ),
        CS,
    ),
    (
        "01968a00-0000-7000-8000-000000000102",
        "medicine",
        "medicine_bio",
        ("Medicine", "Медицина", "Tibbiyot"),
        (
            "Biology and chemistry foundations, practice and entrance exams.",
            "Основы биологии и химии, практика и вступительные экзамены.",
            "Biologiya va kimyo asoslari, amaliyot va kirish imtihonlari.",
        ),
        MEDICINE,
    ),
    (
        "01968a00-0000-7000-8000-000000000103",
        "economics",
        "business_econ",
        ("Economics", "Экономика", "Iqtisodiyot"),
        (
            "Markets, data and policy: the path to an economics degree.",
            "Рынки, данные и политика: путь к экономическому образованию.",
            "Bozorlar, maʼlumotlar va siyosat: iqtisodiy taʼlimga yoʼl.",
        ),
        ECONOMICS,
    ),
]


def upgrade() -> None:
    """Create `trajectories` and `trajectory_progress`; seed the examples."""
    NN: dict[str, bool] = {"nullable": False}  # noqa: N806
    ts = [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
    ]
    op.create_table(
        "trajectories",
        sa.Column("id", sa.Uuid(), **NN),
        sa.Column("slug", sa.String(length=80), **NN),
        sa.Column("field", sa.String(length=20), **NN),
        _json("title", "'{}'::jsonb"),
        _json("description", "'{}'::jsonb"),
        sa.Column("published", sa.Boolean(), server_default=sa.text("false"), **NN),
        _json("stages", "'[]'::jsonb"),
        _json("edges", "'[]'::jsonb"),
        *ts,
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trajectories")),
        sa.UniqueConstraint("slug", name=op.f("uq_trajectories_slug")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_trajectories_field"), "trajectories", ["field"], schema=S
    )
    op.create_table(
        "trajectory_progress",
        sa.Column("id", sa.Uuid(), **NN),
        sa.Column("student_id", sa.Uuid(), **NN),
        sa.Column("trajectory_id", sa.Uuid(), **NN),
        sa.Column("node_id", sa.String(length=40), **NN),
        sa.Column("status", sa.String(length=12), **NN),
        *[c.copy() for c in ts],
        sa.CheckConstraint(
            "status IN ('done', 'in_progress', 'skipped')",
            name=op.f("ck_trajectory_progress_status"),
        ),
        sa.ForeignKeyConstraint(
            ["trajectory_id"],
            [f"{S}.trajectories.id"],
            name=op.f("fk_trajectory_progress_trajectory_id_trajectories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trajectory_progress")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_trajectory_progress_student_id"),
        "trajectory_progress",
        ["student_id"],
        schema=S,
    )
    op.create_index(
        "uq_trajectory_progress_student_node",
        "trajectory_progress",
        ["student_id", "trajectory_id", "node_id"],
        unique=True,
        schema=S,
    )
    # nosemgrep: avoid-sqlalchemy-text -- constant schema, bound parameters
    insert = sa.text(
        f"INSERT INTO {S}.trajectories "
        "(id, slug, field, title, description, published, stages, edges) "
        "VALUES (CAST(:id AS uuid), :slug, :field, CAST(:title AS jsonb), "
        "CAST(:description AS jsonb), true, CAST(:stages AS jsonb), "
        "CAST(:edges AS jsonb)) ON CONFLICT (slug) DO NOTHING"
    )
    for tid, slug, field, title, description, (stages, edges) in SEED:
        op.execute(
            insert.bindparams(
                id=tid,
                slug=slug,
                field=field,
                title=json.dumps(_i18n(title), ensure_ascii=False),
                description=json.dumps(_i18n(description), ensure_ascii=False),
                stages=json.dumps(stages, ensure_ascii=False),
                edges=json.dumps(edges, ensure_ascii=False),
            )
        )


def downgrade() -> None:
    """Drop both tables."""
    op.drop_table("trajectory_progress", schema=S)
    op.drop_table("trajectories", schema=S)
