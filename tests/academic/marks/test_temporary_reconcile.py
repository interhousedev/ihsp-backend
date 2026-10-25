"""TMP-2: the EMIS sync removes temporary marks that EMIS now has."""

from app.modules.academic.infrastructure.orm.temporary_mark import TemporaryMark
from app.shared.ids import new_id
from tests.academic.marks.conftest import Env
from tests.academic.marks.fakes.emis import make_ratings
from tests.academic.marks.world import DAY, MATH_EMIS

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]


async def _add(maker: Maker, env: Env, lesson_id: object, subject_id: object) -> None:
    w = env.world
    async with maker() as session:
        session.add(
            TemporaryMark(
                id=new_id(),
                lesson_id=lesson_id,
                student_id=w.user_id,
                subject_id=subject_id,
                date=DAY,
                value=4,
                author_id=new_id(),
            )
        )
        await session.commit()


async def _left(maker: Maker) -> list[object]:
    async with maker() as session:
        return list(
            (await session.execute(sa.select(TemporaryMark.subject_id))).scalars()
        )


async def test_synced_mark_on_the_date_deletes_the_temporary_mark(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """TMP-2: same student, subject and date in EMIS: the temporary mark goes."""
    w = env.world
    await _add(sessionmaker_in_tx, env, w.math_lesson_1, w.math_id)
    env.emis.set(make_ratings(MATH_EMIS, 3, [("lesson", DAY, 5)], rating=90))

    await env.sync.execute(w.user_id)

    assert await _left(sessionmaker_in_tx) == []


async def test_unchanged_response_still_reconciles_later_temporary_marks(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """TMP-2: a temporary mark added after the EMIS mark goes on the next sync."""
    w = env.world
    env.emis.set(make_ratings(MATH_EMIS, 3, [("lesson", DAY, 5)], rating=90))
    await env.sync.execute(w.user_id)
    await _add(sessionmaker_in_tx, env, w.math_lesson_1, w.math_id)

    await env.sync.execute(w.user_id)

    assert await _left(sessionmaker_in_tx) == []


async def test_other_dates_and_subjects_stay(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """TMP-2: no EMIS mark on that date: the temporary mark stays pending."""
    w = env.world
    await _add(sessionmaker_in_tx, env, w.math_lesson_1, w.math_id)
    env.emis.set(make_ratings(MATH_EMIS, 3, [], rating=90))

    await env.sync.execute(w.user_id)

    assert await _left(sessionmaker_in_tx) == [w.math_id]
