"""Seed a demo opportunities taxonomy and catalog (idempotent, dev only).

IHSP_ENV_FILE=materials/dev.env uv run python scripts/seed_opportunities_demo.py

Real deployments fill the catalog through the admin moderation page; this script
only gives a local stack something to browse. Ids are derived from names, so a
second run updates nothing it already created.
"""

import asyncio
import datetime as dt
import sys
from uuid import NAMESPACE_URL, UUID, uuid5

from app.bootstrap.common import build_container
from app.modules.admission.domain.opportunities import (
    OpportunityDraft,
    OpportunityMaterial,
)
from app.modules.admission.infrastructure.orm.opportunities import (
    OpportunityRow,
    OpportunityTaxonomyRow,
)
from app.settings import load_settings
from app.shared.logging import configure_logging

from sqlalchemy.ext.asyncio import AsyncSession

_NS = uuid5(NAMESPACE_URL, "admission.opportunities.demo")
_SEEDER = uuid5(_NS, "seeder")

# field -> subfield -> subjects; names uz / ru / en
TAXONOMY = (
    (
        ("Aniq fanlar", "Точные науки", "STEM"),
        (
            (
                ("Matematika", "Математика", "Mathematics"),
                (
                    ("Algebra", "Алгебра", "Algebra"),
                    ("Geometriya", "Геометрия", "Geometry"),
                ),
            ),
            (
                ("Informatika", "Информатика", "Computer science"),
                (("Dasturlash", "Программирование", "Programming"),),
            ),
        ),
    ),
    (
        ("Tillar", "Языки", "Languages"),
        (
            (
                ("Ingliz tili", "Английский язык", "English"),
                (
                    (
                        "Akademik ingliz tili",
                        "Академический английский",
                        "Academic English",
                    ),
                ),
            ),
        ),
    ),
)


# Programs: key, title, host, country, location, online, acceptance %, tuition USD
# (0 = free), weeks, ranking, url. Acceptance and tuition are approximate public
# figures that change every year; check the official site before applying.
_Program = tuple[str, str, str, str, str, bool, float | None, int, int, int | None, str]
# fmt: off
# flake8: noqa: E501
_PROGRAMS: tuple[_Program, ...] = (
    ('rsi', 'Research Science Institute (RSI)', 'MIT / CEE', 'USA', 'Cambridge, MA', False, 3.0, 0, 6, 1, 'https://www.cee.org/research-science-institute'),
    ('ssp', 'Summer Science Program (SSP)', 'SSP', 'USA', 'Various campuses', False, 15.0, 6500, 5, 2, 'https://summerscience.org'),
    ('yygs', 'Yale Young Global Scholars (YYGS)', 'Yale University', 'USA', 'New Haven, CT', False, 25.0, 6500, 2, 3, 'https://globalscholars.yale.edu'),
    ('ai4all', 'Stanford AI4ALL', 'Stanford University', 'USA', 'Stanford, CA', False, 15.0, 0, 3, 4, 'https://ai-4-all.org'),
    ('promys', 'PROMYS', 'Boston University', 'USA', 'Boston, MA', False, 30.0, 4500, 6, 5, 'https://promys.org'),
    ('mathcamp', 'Canada/USA Mathcamp', 'Mathcamp', 'USA', 'Various campuses', False, 20.0, 5900, 5, 6, 'https://www.mathcamp.org'),
    ('ross', 'Ross Mathematics Program', 'Ohio State University', 'USA', 'Columbus, OH', False, 40.0, 4500, 6, 7, 'https://rossprogram.org'),
    ('hcssim', 'HCSSiM', 'Hampshire College', 'USA', 'Amherst, MA', False, 25.0, 4000, 6, 8, 'https://hcssim.org'),
    ('mites', 'MITES Summer', 'MIT', 'USA', 'Cambridge, MA', False, 8.0, 0, 6, 9, 'https://mites.mit.edu'),
    ('tasp', 'Telluride Association Summer Program', 'Telluride Association', 'USA', 'Ithaca, MI and others', False, 8.0, 0, 6, 10, 'https://www.tellurideassociation.org'),
    ('sumac', 'Stanford SUMaC', 'Stanford University', 'USA', 'Stanford, CA', True, 15.0, 5000, 4, 11, 'https://sumac.stanford.edu'),
    ('lumiere', 'Lumiere Research Scholar Program', 'Lumiere Education', 'USA', 'Online', True, 20.0, 3900, 12, None, 'https://www.lumiere-education.com'),
    ('polygence', 'Polygence Research Program', 'Polygence', 'USA', 'Online', True, 30.0, 3500, 10, None, 'https://www.polygence.org'),
    ('pioneer', 'Pioneer Academics', 'Pioneer Academics', 'USA', 'Online', True, 25.0, 6000, 12, None, 'https://pioneeracademics.com'),
    ('cty', 'Johns Hopkins CTY Summer Programs', 'Johns Hopkins University', 'USA', 'Baltimore, MD and others', False, 60.0, 5000, 3, None, 'https://cty.jhu.edu'),
    ('harvardsec', 'Harvard Summer School Secondary School Program', 'Harvard University', 'USA', 'Cambridge, MA', False, 70.0, 7500, 7, None, 'https://summer.harvard.edu'),
    ('stanfordsum', 'Stanford Pre-Collegiate Summer Institutes', 'Stanford University', 'USA', 'Stanford, CA', False, 50.0, 6500, 3, None, 'https://summerinstitutes.spcs.stanford.edu'),
    ('columbiasum', 'Columbia Summer High School Program', 'Columbia University', 'USA', 'New York, NY', False, 60.0, 8000, 3, None, 'https://summer.columbia.edu'),
    ('brownpre', 'Brown Pre-College Program', 'Brown University', 'USA', 'Providence, RI', False, 60.0, 5000, 3, None, 'https://precollege.brown.edu'),
    ('cornellsum', 'Cornell Pre-College Studies', 'Cornell University', 'USA', 'Ithaca, NY', False, 60.0, 8000, 3, None, 'https://scl.cornell.edu/summer-college'),
    ('upennlead', 'Penn Summer Academies', 'University of Pennsylvania', 'USA', 'Philadelphia, PA', False, 50.0, 8000, 3, None, 'https://summer.upenn.edu'),
    ('berkeleysum', 'UC Berkeley Pre-College Scholars', 'UC Berkeley', 'USA', 'Berkeley, CA', False, 50.0, 6000, 4, None, 'https://summer.berkeley.edu'),
    ('georgetown', 'Georgetown Summer Immersion', 'Georgetown University', 'USA', 'Washington, DC', False, 50.0, 4500, 3, None, 'https://scs.georgetown.edu'),
    ('notredame', 'Notre Dame Leadership Seminars', 'University of Notre Dame', 'USA', 'Notre Dame, IN', False, 50.0, 2500, 2, None, 'https://precollege.nd.edu'),
    ('duketip', 'Duke TIP Summer Studies', 'Duke University', 'USA', 'Durham, NC', False, 70.0, 4000, 3, None, 'https://tip.duke.edu'),
    ('northwestern', 'Northwestern College Prep Program', 'Northwestern University', 'USA', 'Evanston, IL', False, 60.0, 7500, 4, None, 'https://www.sps.northwestern.edu/cpp'),
    ('caltechqs', 'Caltech Summer Research Connection', 'Caltech', 'USA', 'Pasadena, CA', False, 10.0, 0, 6, None, 'https://sfp.caltech.edu'),
    ('ucsbrmp', 'UCSB Research Mentorship Program', 'UC Santa Barbara', 'USA', 'Santa Barbara, CA', False, 20.0, 4000, 6, None, 'https://rmp.ucsb.edu'),
    ('beaver', 'Beaver Works Summer Institute', 'MIT Lincoln Laboratory', 'USA', 'Cambridge, MA', False, 20.0, 0, 4, None, 'https://beaverworks.ll.mit.edu'),
    ('oxfordsum', 'Oxford Summer Courses (Oxford Scholastica)', 'Oxford Scholastica', 'UK', 'Oxford', False, 80.0, 5500, 2, None, 'https://www.oxfordscholastica.com'),
    ('cambridgesum', 'Cambridge Summer Programs', 'Cambridge Immerse', 'UK', 'Cambridge', False, 70.0, 5000, 2, None, 'https://www.immerse.education'),
    ('lseyoung', 'LSE Summer School for Young Learners', 'London School of Economics', 'UK', 'London', False, 85.0, 4500, 2, None, 'https://www.lse.ac.uk/study-at-lse/summer-schools'),
    ('imperial', 'Imperial College Summer School', 'Imperial College London', 'UK', 'London', False, 70.0, 3500, 2, None, 'https://www.imperial.ac.uk/summer-school'),
    ('ethzurich', 'ETH Zurich Summer School', 'ETH Zurich', 'Switzerland', 'Zurich', False, 30.0, 1500, 2, None, 'https://ethz.ch/students/en/studies/summer-schools.html'),
    ('nus', 'NUS Summer Enrichment', 'National University of Singapore', 'Singapore', 'Singapore', False, 60.0, 3000, 2, None, 'https://www.nus.edu.sg'),
    ('kaust', 'KAUST Gifted Student Program', 'KAUST', 'Saudi Arabia', 'Thuwal', False, 10.0, 0, 6, None, 'https://www.kaust.edu.sa/en/study/gifted-students'),
    ('mext', 'MEXT Summer Camp (Tokyo Tech)', 'Tokyo Institute of Technology', 'Japan', 'Tokyo', False, 30.0, 1200, 2, None, 'https://www.titech.ac.jp/english'),
    ('emory', 'Emory Pre-College Program', 'Emory University', 'USA', 'Atlanta, GA', False, 60.0, 6000, 3, None, 'https://precollege.emory.edu'),
    ('coursera', 'Coursera for Teens: University Courses Online', 'Coursera', 'USA', 'Online', True, None, 0, 8, None, 'https://www.coursera.org'),
    ('mitoc', 'MIT OpenCourseWare Scholar', 'MIT', 'USA', 'Online', True, None, 0, 12, None, 'https://ocw.mit.edu'),
)
# fmt: on


def _id(*parts: str) -> UUID:
    return uuid5(_NS, "/".join(parts))


def _names(t: tuple[str, str, str]) -> dict[str, str]:
    return dict(zip(("uz", "ru", "en"), t))


def _entries(year: int) -> list[tuple[str, OpportunityDraft]]:
    algebra = _id("Mathematics", "Algebra")
    programming = _id("Computer science", "Programming")
    english = _id("English", "Academic English")
    return [
        (
            "sat",
            OpportunityDraft(
                kind="exam",
                title="SAT",
                summary="College admission test in reading, writing and math.",
                url="https://satsuite.collegeboard.org/sat",
                provider="College Board",
                subject_ids=(algebra, english),
                grades=(11, 12),
                registration_deadlines=(),
                exam_dates=(),
                last_year_dates=(dt.date(year - 1, 10, 5), dt.date(year - 1, 12, 7)),
                recurrence=None,
                lms_course_id=None,
                materials=(
                    OpportunityMaterial(
                        "link",
                        "Khan Academy SAT prep",
                        "https://www.khanacademy.org/test-prep/sat",
                        None,
                        None,
                    ),
                ),
                note=None,
            ),
        ),
        (
            "ielts",
            OpportunityDraft(
                kind="certification",
                title="IELTS Academic",
                summary="English test accepted by most universities abroad.",
                url="https://ielts.org",
                provider="British Council / IDP",
                subject_ids=(english,),
                grades=(10, 11),
                registration_deadlines=(),
                exam_dates=(),
                last_year_dates=(),
                recurrence="FREQ=MONTHLY;BYMONTHDAY=15",
                lms_course_id=None,
                materials=(),
                note=None,
            ),
        ),
        (
            "usaco",
            OpportunityDraft(
                kind="event",
                title="USACO",
                summary="Online programming olympiad with four contests a season.",
                url="https://usaco.org",
                provider="USACO",
                subject_ids=(programming, algebra),
                grades=(9, 10, 11),
                registration_deadlines=(),
                exam_dates=(),
                last_year_dates=(dt.date(year - 1, 12, 13), dt.date(year, 1, 17)),
                recurrence=None,
                lms_course_id=None,
                materials=(),
                note=None,
            ),
        ),
    ]


def _program_rows() -> list[OpportunityRow]:
    rows = []
    for key, title, host, country, loc, online, acc, fee, weeks, rank, url in _PROGRAMS:
        payload = OpportunityDraft(
            kind="program",
            title=title,
            summary=f"{title}: a pre-college program hosted by {host}. "
            "Acceptance rate and tuition are approximate.",
            url=url,
            provider=host,
            grades=(10, 11),
            country=country,
            location=loc,
            online=online,
            acceptance_rate=acc,
            tuition_usd=fee,
            host_institution=host,
            duration_weeks=weeks,
            ranking=rank,
        ).to_payload()
        rows.append(
            OpportunityRow(
                id=_id("program", key),
                kind="program",
                title=title,
                payload=payload,
                subject_ids=[],
                created_by=_SEEDER,
            )
        )
    return rows


async def _add_missing(s: AsyncSession, rows: list[OpportunityRow]) -> None:
    for row in rows:
        if await s.get(OpportunityRow, row.id) is None:
            s.add(row)


async def _run() -> None:
    from app.interfaces.jobs.broker import broker

    settings = load_settings()
    configure_logging(settings.log_level, json_logs=False)
    await broker.startup()
    container = await build_container(settings, process="identity")
    try:
        async with container.sessionmaker() as s:
            for fi, (field, subfields) in enumerate(TAXONOMY):
                fid = _id(field[2])
                if await s.get(OpportunityTaxonomyRow, fid) is None:
                    s.add(
                        OpportunityTaxonomyRow(
                            id=fid,
                            level="field",
                            parent_id=None,
                            names=_names(field),
                            position=fi,
                        )
                    )
                for si, (sub, subjects) in enumerate(subfields):
                    sid = _id(sub[2])
                    if await s.get(OpportunityTaxonomyRow, sid) is None:
                        s.add(
                            OpportunityTaxonomyRow(
                                id=sid,
                                level="subfield",
                                parent_id=fid,
                                names=_names(sub),
                                position=si,
                            )
                        )
                    for ji, subj in enumerate(subjects):
                        jid = _id(sub[2], subj[2])
                        if await s.get(OpportunityTaxonomyRow, jid) is None:
                            s.add(
                                OpportunityTaxonomyRow(
                                    id=jid,
                                    level="subject",
                                    parent_id=sid,
                                    names=_names(subj),
                                    position=ji,
                                )
                            )
                await s.flush()
            for key, draft in _entries(container.clock.now().year):
                oid = _id("opportunity", key)
                if await s.get(OpportunityRow, oid) is not None:
                    continue
                payload = draft.to_payload()
                s.add(
                    OpportunityRow(
                        id=oid,
                        kind=draft.kind,
                        title=payload["title"],
                        payload=payload,
                        subject_ids=payload["subject_ids"],
                        created_by=_SEEDER,
                    )
                )
            await _add_missing(s, _program_rows())
            await s.commit()
    finally:
        await container.close()
        await broker.shutdown()


def main() -> int:
    """Run the seed."""
    asyncio.run(_run())
    sys.stdout.write("Opportunities demo taxonomy and catalog seeded.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
