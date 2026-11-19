"""admission opportunity kind `research` and real courses, tests and events.

Allows the opportunity kind `research` and seeds verified courses, tests,
research programs, fellowships and events, each tagged with catalog study
fields (`study_field_ids`) so the catalog can sort "for you".

Revision ID: admission_0040_opp_research
Revises: admission_0039_round_scea
Create Date: 2026-11-30 10:00:00.000000
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0040_opp_research"
down_revision: str | Sequence[str] | None = "admission_0039_round_scea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
_JSON = postgresql.JSONB(astext_type=sa.Text())
_OLD = (
    "kind IN ('exam', 'certification', 'course', 'event', 'recurring', 'program',"
    " 'scholarship')"
)
_NEW = (
    "kind IN ('exam', 'certification', 'course', 'event', 'recurring', 'program',"
    " 'scholarship', 'research')"
)
_NS = UUID("0b6f4f0e-7a43-4c1e-9d0a-5e2c1b7a0040")
_SYSTEM = UUID(int=0)

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
    "org_id": None,
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
    "study_field_ids": [],
    "materials": [],
}

_CS = ["computer_science"]
_FREE = {"tuition_usd": 0, "online": True}


def _course(
    title: str, provider: str, url: str, summary: str, fields: list[str], **more: Any
) -> dict[str, Any]:
    return {
        "kind": "course",
        "title": title,
        "provider": provider,
        "url": url,
        "source_url": url,
        "summary": summary,
        "study_field_ids": fields,
        **more,
    }


def _opps() -> list[dict[str, Any]]:
    return [
        _course(
            "Elements of AI",
            "University of Helsinki and MinnaLearn",
            "https://www.elementsofai.com/",
            "Free online course that explains what AI is and what it can and "
            "cannot do, with no programming required.",
            ["computer_science"],
            **_FREE,
        ),
        _course(
            "Python Programming MOOC",
            "University of Helsinki",
            "https://programming-26.mooc.fi/",
            "Free online introduction to programming in Python with automatically "
            "checked exercises.",
            _CS,
            **_FREE,
        ),
        _course(
            "Full Stack Open",
            "University of Helsinki",
            "https://fullstackopen.com/en/",
            "Free course on modern web development with React, Node.js and "
            "TypeScript.",
            ["computer_science", "information_systems"],
            **_FREE,
        ),
        _course(
            "MITx 6.00.1x: Introduction to Computer Science and Programming "
            "Using Python",
            "MIT on edX",
            "https://www.edx.org/learn/computer-programming/"
            "massachusetts-institute-of-technology-introduction-to-computer-"
            "science-and-programming-7",
            "MIT's introductory programming course in Python. Free to audit; "
            "a verified certificate is optional and paid.",
            ["computer_science", "engineering"],
            online=True,
        ),
        _course(
            "MIT OpenCourseWare: Linear Algebra (18.06)",
            "MIT OpenCourseWare",
            "https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/",
            "Gilbert Strang's full linear algebra course with video lectures and "
            "problem sets, free and open.",
            ["mathematics", "computer_science", "engineering", "physics"],
            **_FREE,
        ),
        _course(
            "Learning How to Learn",
            "Deep Teaching Solutions on Coursera",
            "https://www.coursera.org/learn/learning-how-to-learn",
            "Study techniques from neuroscience and psychology for any subject. "
            "Free to audit; the certificate is paid.",
            ["psychology", "education", "liberal_arts"],
            online=True,
        ),
        _course(
            "Machine Learning Specialization",
            "DeepLearning.AI and Stanford on Coursera",
            "https://www.coursera.org/specializations/machine-learning-introduction",
            "Andrew Ng's beginner-friendly introduction to machine learning. "
            "Free to audit; the certificate is paid.",
            ["computer_science", "mathematics"],
            online=True,
        ),
        _course(
            "CS50's Introduction to Artificial Intelligence with Python",
            "Harvard University",
            "https://cs50.harvard.edu/ai/",
            "Free Harvard course on search, knowledge, machine learning and "
            "language models, taught in Python.",
            ["computer_science", "mathematics"],
            **_FREE,
        ),
        _course(
            "Financial Markets",
            "Yale University on Coursera",
            "https://www.coursera.org/learn/financial-markets-global",
            "Robert Shiller's course on how financial markets and institutions "
            "work. Free to audit; the certificate is paid.",
            ["economics", "business"],
            online=True,
        ),
        {
            "kind": "certification",
            "title": "TOEFL iBT",
            "provider": "ETS",
            "url": "https://www.ets.org/toefl.html",
            "source_url": "https://www.ets.org/toefl.html",
            "summary": "English proficiency test accepted by universities worldwide. "
            "Paid; the test is taken at a test centre or at home.",
            "study_field_ids": ["literature_languages", "humanities"],
        },
        {
            "kind": "certification",
            "title": "Duolingo English Test",
            "provider": "Duolingo",
            "url": "https://englishtest.duolingo.com/",
            "source_url": "https://englishtest.duolingo.com/",
            "summary": "Online adaptive English proficiency test accepted by many "
            "universities. Paid; taken on your own computer.",
            "online": True,
            "study_field_ids": ["literature_languages", "humanities"],
        },
        {
            "kind": "certification",
            "title": "Cambridge C1 Advanced",
            "provider": "Cambridge English",
            "url": "https://www.cambridgeenglish.org/exams-and-tests/"
            "qualifications/advanced/",
            "source_url": "https://www.cambridgeenglish.org/exams-and-tests/"
            "qualifications/advanced/",
            "summary": "Cambridge qualification showing advanced English, recognised "
            "by universities and employers. Paid; taken at an authorised centre.",
            "study_field_ids": ["literature_languages", "humanities"],
        },
        {
            "kind": "certification",
            "title": "Google Career Certificates",
            "provider": "Google on Coursera",
            "url": "https://grow.google/certificates/",
            "source_url": "https://grow.google/certificates/",
            "summary": "Self-paced job-ready programs in data analytics, UX design, "
            "project management and more. Paid subscription; financial aid is "
            "available on Coursera.",
            "online": True,
            "study_field_ids": [
                "computer_science",
                "information_systems",
                "design",
                "business",
            ],
        },
        {
            "kind": "certification",
            "title": "AWS Certified Cloud Practitioner",
            "provider": "Amazon Web Services",
            "url": "https://aws.amazon.com/certification/certified-cloud-practitioner/",
            "source_url": "https://aws.amazon.com/certification/"
            "certified-cloud-practitioner/",
            "summary": "Entry-level AWS credential covering cloud concepts, core "
            "services, security and billing. Paid exam; no prerequisites.",
            "study_field_ids": ["computer_science", "information_systems"],
        },
        {
            "kind": "scholarship",
            "title": "Rise",
            "provider": "Schmidt Futures and the Rhodes Trust",
            "url": "https://www.risefortheworld.org/",
            "source_url": "https://www.risefortheworld.org/",
            "summary": "Global talent program for ages 15 to 17 that offers its "
            "winners lifelong support: scholarships, mentorship and funding.",
            "award_type": "fellowship",
            "scope": "international",
            "coverage": ["stipend"],
            "online": True,
            "eligibility": "Open to young people worldwide who are 15 to 17.",
            "study_field_ids": ["social_sciences", "liberal_arts"],
        },
        {
            "kind": "research",
            "title": "Beamline for Schools",
            "provider": "CERN",
            "url": "https://beamlineforschools.cern/",
            "source_url": "https://beamlineforschools.cern/",
            "summary": "Physics competition where school teams propose an experiment; "
            "winners run it at a particle beamline, with travel, stay and meals "
            "covered.",
            "scope": "international",
            "tuition_usd": 0,
            "eligibility": "Teams of 5 to 9 high-school students aged 16 or older, "
            "with an adult coach; open to students worldwide.",
            "study_field_ids": ["physics", "engineering", "natural_sciences"],
        },
        {
            "kind": "research",
            "title": "Wolfram Summer Research Program",
            "provider": "Wolfram Research",
            "url": "https://education.wolfram.com/summer-research/",
            "source_url": "https://education.wolfram.com/summer-research-high-school/",
            "summary": "Project-based summer research for high-school students using "
            "the Wolfram Language across STEM fields. Paid; need-based financial "
            "aid is offered.",
            "eligibility": "International students are accepted and must arrange "
            "their own visas; applicants must be under 18 when the program ends.",
            "study_field_ids": [
                "computer_science",
                "mathematics",
                "natural_sciences",
                "physics",
            ],
        },
        {
            "kind": "research",
            "title": "Regeneron International Science and Engineering Fair",
            "provider": "Society for Science",
            "url": "https://www.societyforscience.org/isef/",
            "source_url": "https://www.societyforscience.org/isef/",
            "summary": "The largest pre-university science fair, where students "
            "present their own research projects.",
            "scope": "international",
            "eligibility": "Grades 9 to 12; international students qualify through "
            "an ISEF-affiliated national or regional fair in their country.",
            "study_field_ids": ["natural_sciences", "engineering", "biology"],
        },
        {
            "kind": "event",
            "title": "International Olympiad in Informatics",
            "provider": "IOI",
            "url": "https://ioinformatics.org/",
            "source_url": "https://ioinformatics.org/",
            "summary": "Annual worldwide algorithmic programming olympiad for "
            "secondary-school students, played by national teams.",
            "scope": "international",
            "eligibility": "Students join through their national team selection.",
            "study_field_ids": _CS,
        },
        {
            "kind": "event",
            "title": "International Mathematical Olympiad",
            "provider": "IMO",
            "url": "https://www.imo-official.org/",
            "source_url": "https://www.imo-official.org/",
            "summary": "The world championship mathematics competition for "
            "high-school students, played by national teams.",
            "scope": "international",
            "eligibility": "Students join through their national team selection.",
            "study_field_ids": ["mathematics"],
        },
        {
            "kind": "event",
            "title": "NASA International Space Apps Challenge",
            "provider": "NASA",
            "url": "https://www.spaceappschallenge.org/",
            "source_url": "https://www.spaceappschallenge.org/",
            "summary": "Free global hackathon where teams solve Earth and space "
            "problems with open NASA data, in person or virtually.",
            "tuition_usd": 0,
            "online": True,
            "study_field_ids": [
                "computer_science",
                "engineering",
                "physics",
                "environmental_science",
            ],
        },
        {
            "kind": "event",
            "title": "Technovation Girls",
            "provider": "Technovation",
            "url": "https://technovationchallenge.org/",
            "source_url": "https://technovationchallenge.org/get-involved/students/",
            "summary": "Free worldwide challenge where teams build a technology "
            "solution to a community problem. No programming experience needed.",
            "tuition_usd": 0,
            "online": True,
            "eligibility": "Girls and nonbinary participants aged 8 to 18, in teams "
            "of one to five.",
            "study_field_ids": ["computer_science", "design", "social_sciences"],
        },
    ]


def _id(title: str) -> UUID:
    return uuid5(_NS, "opp:" + title)


def upgrade() -> None:
    """Allow `research` and seed the real catalog entries."""
    op.drop_constraint("ck_opportunities_kind", "opportunities", schema=S)
    op.create_check_constraint(
        op.f("ck_opportunities_kind"), "opportunities", _NEW, schema=S
    )
    opps = sa.table(
        "opportunities",
        sa.column("id", sa.Uuid()),
        sa.column("kind", sa.String()),
        sa.column("title", sa.String()),
        sa.column("payload", _JSON),
        sa.column("created_by", sa.Uuid()),
        schema=S,
    )
    op.bulk_insert(
        opps,
        [
            {
                "id": _id(o["title"]),
                "kind": o["kind"],
                "title": o["title"],
                "payload": {**_BASE, **o},
                "created_by": _SYSTEM,
            }
            for o in _opps()
        ],
    )


def downgrade() -> None:
    """Drop the seeds and every `research` entry, then restore the old kinds."""
    ids = ", ".join(f"'{_id(o['title'])}'" for o in _opps())
    op.execute(
        f"DELETE FROM {S}.opportunities WHERE kind = 'research' OR id IN ({ids})"
    )
    op.drop_constraint("ck_opportunities_kind", "opportunities", schema=S)
    op.create_check_constraint(
        op.f("ck_opportunities_kind"), "opportunities", _OLD, schema=S
    )
