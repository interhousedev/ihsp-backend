"""admission supplemental essay prompts per institution and cycle, with a seed.

Revision ID: admission_0033_supp_prompts
Revises: admission_0032_logo_zoom_advice
Create Date: 2026-11-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid_utils.compat import uuid7

# revision identifiers, used by Alembic.
revision: str = "admission_0033_supp_prompts"
down_revision: str | Sequence[str] | None = "admission_0032_logo_zoom_advice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"

# (prompt, word limit, required); the source is the school's official page.
_P = tuple[str, int | None, bool]

_HARVARD_SAME: list[_P] = [
    (
        "Describe a time when you strongly disagreed with someone about an idea or"
        " issue. How did you communicate or engage with this person? What did you"
        " learn from this experience?",
        150,
        True,
    ),
    (
        "Briefly describe any of your extracurricular activities, employment"
        " experience, travel, or family responsibilities that have shaped who you"
        " are.",
        150,
        True,
    ),
    ("How do you hope to use your Harvard education in the future?", 150, True),
    ("Top 3 things your roommates might like to know about you.", 150, True),
]

_YALE_SHORT: list[_P] = [
    (
        "Tell us about a topic or idea that excites you and is related to one or"
        " more academic areas you selected above. Why are you drawn to it?",
        200,
        True,
    ),
    ("What inspires you? (200 characters)", None, True),
    (
        "If you could teach a college course, write a book, or create an original"
        " piece of art of any kind, what would it be? (200 characters)",
        None,
        True,
    ),
    (
        "Other than a family member, who is someone who has had a significant"
        " influence on you? What has been the impact of their influence?"
        " (200 characters)",
        None,
        True,
    ),
    (
        "What is something about you that is not included anywhere else in your"
        " application? (200 characters)",
        None,
        True,
    ),
    (
        "Reflect on a time when you discussed an issue of importance with someone"
        " holding an opinion different from yours. Why was the experience"
        " meaningful to you?",
        400,
        False,
    ),
    (
        "Reflect on your membership in a community to which you feel connected. Why"
        " is this community meaningful to you? You may define community however you"
        " like.",
        400,
        False,
    ),
    (
        "Reflect on an element of your personal experience that you feel will"
        " enrich your college. How has it shaped you?",
        400,
        False,
    ),
]

_COLUMBIA_LIST: _P = (
    "List a selection of texts, resources and outlets that have contributed to your"
    " intellectual development outside of academic courses, including but not"
    " limited to books, journals, websites, podcasts, essays, plays, presentations,"
    " videos, museums and other content that you enjoy.",
    100,
    True,
)
_COLUMBIA_WHY: list[_P] = [
    (
        "Why are you interested in attending Columbia University? We encourage you"
        " to consider the aspect(s) that you find unique and compelling about"
        " Columbia.",
        150,
        True,
    ),
    (
        "What attracts you to your preferred areas of study at Columbia College or"
        " Columbia Engineering?",
        150,
        True,
    ),
]

_MIT: list[_P] = [
    (
        "What field of study appeals to you the most right now? Tell us more about"
        " why this field of study at MIT appeals to you.",
        100,
        True,
    ),
    (
        "We know you lead a busy life, full of activities, many of which are"
        " required of you. Tell us about something you do simply for the pleasure"
        " of it.",
        200,
        True,
    ),
    (
        "How has the world you come from—including your opportunities, experiences,"
        " and challenges—shaped your dreams and aspirations?",
        200,
        True,
    ),
    (
        "MIT brings people with diverse backgrounds and experiences together to"
        " better the lives of others. Our students work to improve their"
        " communities in different ways, from tackling the world's biggest"
        " challenges to being a good friend. Describe one way you have collaborated"
        " with people who are different from you to contribute to your community.",
        200,
        True,
    ),
    (
        "Tell us about a challenge that you've faced or something that didn't go"
        " according to plan that you feel comfortable sharing. How did you manage"
        " the situation?",
        200,
        True,
    ),
]

_STANFORD: list[_P] = [
    ("What is the most significant challenge that society faces today?", 50, True),
    ("How did you spend your last two summers?", 50, True),
    (
        "What historical moment or event do you wish you could have witnessed?",
        50,
        True,
    ),
    (
        "Briefly elaborate on one of your extracurricular activities, a job you"
        " hold, or responsibilities you have for your family.",
        50,
        True,
    ),
    ("List five things that are important to you.", 50, True),
    (
        "The Stanford community is deeply curious and driven to learn in and out of"
        " the classroom. Reflect on an idea or experience that makes you genuinely"
        " excited about learning.",
        250,
        True,
    ),
    (
        "Virtually all of Stanford's undergraduates live on campus. Write a note to"
        " your future roommate that reveals something about you or that will help"
        " your roommate—and us—get to know you better.",
        250,
        True,
    ),
    (
        "Please describe what aspects of your life experiences, interests and"
        " character would help you make a distinctive contribution as an"
        " undergraduate to Stanford University.",
        250,
        True,
    ),
]

_PRINCETON: list[_P] = [
    (
        "As a research institution that also prides itself on its liberal arts"
        " curriculum, Princeton allows students to explore areas across the"
        " humanities and the arts, the natural sciences, and the social sciences."
        " What academic areas most pique your curiosity, and how do the programs"
        " offered at Princeton suit your particular interests?",
        250,
        True,
    ),
    (
        "Princeton values community and encourages students, faculty, staff and"
        " leadership to engage in respectful conversations that can expand their"
        " perspectives and challenge their ideas and beliefs. As a prospective"
        " member of this community, reflect on how your lived experiences will"
        " impact the conversations you will have in the classroom, the dining hall"
        " or other campus spaces. What lessons have you learned in life thus far?"
        " What will your classmates learn from you? In short, how has your lived"
        " experience shaped you?",
        500,
        True,
    ),
    (
        "Princeton has a longstanding commitment to service and civic engagement."
        " Tell us how your story intersects (or will intersect) with these ideals.",
        250,
        True,
    ),
    ("What is a new skill you would like to learn in college?", 50, True),
    ("What brings you joy?", 50, True),
    ("What song represents the soundtrack of your life at this moment?", 50, True),
]

_PENN: list[_P] = [
    (
        "Write a short thank-you note to someone you have not yet thanked and would"
        " like to acknowledge. (We encourage you to share this note with that"
        " person, if possible, and reflect on the experience!)",
        200,
        True,
    ),
    (
        "How will you explore community at Penn? Consider how Penn will help shape"
        " your perspective, and how your experiences and perspective will help"
        " shape Penn.",
        200,
        True,
    ),
]

SEED: dict[str, tuple[str, dict[str, list[_P]]]] = {
    "harvard": (
        "https://college.harvard.edu/guides/application-tips",
        {
            "2024-25": [
                (
                    "Harvard has long recognized the importance of enrolling a"
                    " diverse student body. How will the life experiences that"
                    " shape who you are today enable you to contribute to Harvard?",
                    150,
                    True,
                ),
                *_HARVARD_SAME,
            ],
            "2025-26": [
                (
                    "Harvard has long recognized the importance of enrolling a"
                    " student body with a diversity of perspectives and"
                    " experiences. How will the life experiences that shaped who"
                    " you are today enable you to contribute to Harvard?",
                    150,
                    True,
                ),
                *_HARVARD_SAME,
            ],
        },
    ),
    "yale": (
        "https://admissions.yale.edu/essay-topics",
        {
            "2024-25": [
                ("What is it about Yale that has led you to apply?", 125, True),
                *_YALE_SHORT,
            ],
            "2025-26": [
                (
                    "Reflect on how your interests, values, and/or experiences have"
                    " drawn you to Yale.",
                    125,
                    True,
                ),
                *_YALE_SHORT,
            ],
        },
    ),
    "columbia": (
        "https://undergrad.admissions.columbia.edu/apply/process/columbia-questions",
        {
            "2024-25": [
                _COLUMBIA_LIST,
                (
                    "A hallmark of the Columbia experience is being able to learn"
                    " and thrive in an equitable and inclusive community with a"
                    " wide range of perspectives. Tell us about an aspect of your"
                    " own perspective, viewpoint or lived experience that is"
                    " important to you, and describe how it has shaped the way you"
                    " would learn from and contribute to Columbia's diverse and"
                    " collaborative community.",
                    150,
                    True,
                ),
                (
                    "In college/university, students are often challenged in ways"
                    " that they could not predict or anticipate. It is important to"
                    " us, therefore, to understand an applicant's ability to"
                    " navigate through adversity. Please describe a barrier or"
                    " obstacle you have faced and discuss the personal qualities,"
                    " skills or insights you have developed as a result.",
                    150,
                    True,
                ),
                *_COLUMBIA_WHY,
            ],
            "2025-26": [
                _COLUMBIA_LIST,
                (
                    "Tell us about an aspect of your life so far or your lived"
                    " experience that is important to you, and describe how it has"
                    " shaped the way you would learn from and contribute to"
                    " Columbia's multidimensional and collaborative environment.",
                    150,
                    True,
                ),
                (
                    "In college/university, students are often challenged in ways"
                    " that they could not anticipate. Please describe a situation"
                    " in which you have navigated through adversity and discuss how"
                    " you changed as a result.",
                    150,
                    True,
                ),
                *_COLUMBIA_WHY,
                (
                    "At Columbia, students representing a wide range of"
                    " perspectives are invited to live and learn together. In such"
                    " a community, questions and debates naturally arise. Please"
                    " describe a time when you did not agree with someone and"
                    " discuss how you engaged with them and what you took away from"
                    " the interaction.",
                    150,
                    True,
                ),
            ],
        },
    ),
    "mit": (
        "https://mitadmissions.org/apply/firstyear/essays-activities-academics/",
        {"2024-25": _MIT, "2025-26": _MIT},
    ),
    "stanford": (
        "https://admission.stanford.edu/apply/freshman/essays.html",
        {"2024-25": _STANFORD, "2025-26": _STANFORD},
    ),
    "princeton": (
        "https://admission.princeton.edu/apply/princeton-specific-questions",
        {"2024-25": _PRINCETON, "2025-26": _PRINCETON},
    ),
    "upenn": (
        "https://admissions.upenn.edu/how-to-apply/first-year-applicants/"
        "writing-supplement",
        {"2024-25": _PENN, "2025-26": _PENN},
    ),
    "jhu": (
        "https://apply.jhu.edu/application-process/essays/",
        {
            "2024-25": [
                (
                    "Tell us about an aspect of your identity (e.g., race, gender,"
                    " sexuality, religion, community, etc.) or a life experience"
                    " that has shaped you as an individual and how that influenced"
                    " what you'd like to pursue in college at Hopkins.",
                    350,
                    True,
                ),
            ],
            "2025-26": [
                (
                    "As we commemorate the university's sesquicentennial—150 years"
                    " since its founding—we continue to celebrate first steps just"
                    " as much as final achievements. Tell us about an important"
                    " first in your life—big or small—that has shaped you.",
                    350,
                    True,
                ),
            ],
        },
    ),
    "gatech": (
        "https://admission.gatech.edu/first-year/personal-essays",
        {
            "2025-26": [
                (
                    "Why do you want to study your chosen major, and why do you"
                    " want to study that major at Georgia Tech?",
                    300,
                    True,
                ),
            ],
        },
    ),
    "cornell": (
        "https://admissions.cornell.edu/apply/first-year-applicants/"
        "cornell-essay-questions",
        {
            "2025-26": [
                (
                    "We all contribute to, and are influenced by, the communities"
                    " that are meaningful to us. Share how you've been shaped by"
                    " one of the communities you belong to.",
                    350,
                    True,
                ),
            ],
        },
    ),
}


def upgrade() -> None:
    """Create the prompts table and seed the known catalog schools."""
    table = op.create_table(
        "supp_prompts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("cycle", sa.String(length=7), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("word_limit", sa.Integer(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
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
        sa.CheckConstraint(
            "cycle ~ '^[0-9]{4}-[0-9]{2}$'", name=op.f("ck_supp_prompts_cycle_format")
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_supp_prompts_position_nonnegative")
        ),
        sa.CheckConstraint(
            "word_limit IS NULL OR word_limit BETWEEN 1 AND 5000",
            name=op.f("ck_supp_prompts_word_limit_range"),
        ),
        sa.CheckConstraint(
            "source_url IS NULL OR source_url LIKE 'https://%'",
            name=op.f("ck_supp_prompts_source_url_https"),
        ),
        sa.CheckConstraint(
            "char_length(prompt) <= 4000", name=op.f("ck_supp_prompts_prompt_length")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            [f"{S}.institutions.id"],
            name=op.f("fk_supp_prompts_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supp_prompts")),
        sa.UniqueConstraint(
            "institution_id",
            "cycle",
            "position",
            name=op.f("uq_supp_prompts_institution_id"),
        ),
        schema=S,
    )
    op.create_index(
        "ix_supp_prompts_institution_cycle",
        "supp_prompts",
        ["institution_id", "cycle"],
        schema=S,
    )
    _seed(table)


def _seed(table: sa.Table) -> None:
    """Insert the prompts of every seeded school the catalog has."""
    conn = op.get_bind()
    rows = []
    for slug, (url, cycles) in SEED.items():
        inst = conn.execute(
            # nosemgrep: avoid-sqlalchemy-text -- constant schema, bound parameters
            sa.text(f"SELECT id FROM {S}.institutions WHERE slug = :slug"),
            {"slug": slug},
        ).scalar()
        if inst is None:
            continue
        for cycle, prompts in cycles.items():
            for pos, (text, limit, required) in enumerate(prompts):
                rows.append(
                    {
                        "id": uuid7(),
                        "institution_id": inst,
                        "cycle": cycle,
                        "position": pos,
                        "prompt": text,
                        "word_limit": limit,
                        "required": required,
                        "source_url": url,
                    }
                )
    if rows:
        op.bulk_insert(table, rows)


def downgrade() -> None:
    """Drop the prompts table with its seed."""
    op.drop_index("ix_supp_prompts_institution_cycle", "supp_prompts", schema=S)
    op.drop_table("supp_prompts", schema=S)
