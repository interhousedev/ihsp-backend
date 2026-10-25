"""Demo homework for the demo groups: last, this and next week, with files and ticks.

Every lesson of those weeks that is not a control gets, on most days, homework from its
teacher, due on a school day (Mon to Fri). Last week's homework is partly ticked, so
some of it is overdue; this week's is ticked early on in places. A third of the
homework carries an attached file, and the first lesson of a subject in this or next
week carries a material. Everything goes through the real use cases, and a lesson that
already has homework is left alone, so a second run changes nothing.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.seed.demo_files import DEMO_FILES
from app.bootstrap.seed.students import EMIS_LOGINS
from app.modules.identity.domain.login_name import base_login
from app.modules.identity.infrastructure.emis.fake import FAKE_STUDENTS
from app.modules.identity.infrastructure.emis.fake_schedule import digest
from app.shared.actor import Actor, Role
from app.shared.clock import local_today
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.text import title_case

import structlog

log = structlog.get_logger(__name__)

HOMEWORK_TEXTS: dict[int, tuple[str, ...]] = {  # EMIS subject id -> homework texts
    101: (
        "Решить №125–131 (производная сложной функции). Ответы сверить с книгой.",
        "Vazifa: 5-mashq, 1–6-misollar. Hosilalarni toping va natijani tekshiring.",
        "Интегралы №210–216 (табличные и подстановкой). Проверить дифференцированием.",
    ),
    102: (
        "Задачи 14–18 на закон Ома для участка цепи. Записать «Дано» и решение.",
        "Tebranish davri bo'yicha laboratoriya jadvalini to'ldiring va xulosa yozing.",
        "Повторить §21 (сила трения), письменно ответить на вопросы 1–4 после текста.",
    ),
    103: (
        "Learn the 20 new words from Unit 6 and write five sentences with them.",
        "Read pages 84–86 and answer the comprehension questions in writing.",
        "Write 80–100 words about your favourite place in Tashkent.",
    ),
    104: (
        "Упражнение 312: синтаксический разбор, выписать правила пунктуации.",
        "Написать сочинение-рассуждение «Что такое честность?» (150–200 слов).",
        "Упражнение 318: вставить пропущенные буквы и объяснить написание.",
    ),
    105: (
        "Mashq 45: gaplardagi kelishiklarni aniqlang va daftarga ko'chirib yozing.",
        "'O'tkan kunlar' 10–12-boblarni o'qing, qahramonlar haqida 5 ta gap yozing.",
        "She'r yod oling: 8 misra, ifodali o'qishga tayyorlaning.",
    ),
    106: (
        "§17: прочитать параграф, составить хронологическую таблицу из 6 событий.",
        "Tarix: Amir Temur davlati haqida bir sahifali konspekt tayyorlang.",
        "Подготовить план ответа по теме «Реформы Петра I» (6 пунктов).",
    ),
    107: (
        "Написать программу на Python: сумма цифр введённого числа (три примера).",
        "Informatika: Excel'da 10 qatorli jadval tuzing, o'rtacha ballni hisoblang.",
        "Повторить циклы while и for, решить задачи 4–6 из практикума.",
    ),
    108: (
        "Уравнять 8 реакций из задачника (§9), указать тип каждой реакции.",
        "Kimyo: molyar massa bo'yicha 6 ta masalani yeching, javoblarni yozing.",
        "Подготовить краткий конспект о валентности элементов главной подгруппы.",
    ),
}
# Materials: the first lesson of the subject in this or next week gets the file.
MATERIALS: dict[int, str] = {
    101: "derivatives-worksheet.pdf",
    102: "ohm-circuit.png",
    103: "unit6-notes.txt",
    108: "reaction-types.docx",
}
# Homework files: attached to about a third of the subject's homework lessons.
HOMEWORK_FILES: dict[int, str] = {
    101: "derivatives-worksheet.pdf",
    102: "ohm-circuit.png",
    103: "unit6-notes.txt",
    106: "history-plan.docx",
}
HOMEWORK_SHARE = 7  # out of every ten lessons get homework
_NON_HOMEWORK_KINDS = ("midterm", "final")
_FAKE_BY_LOGIN = {student.login: student for student in FAKE_STUDENTS}


def demo_student_logins() -> tuple[str, ...]:
    """The login of each demo student, as the registration makes it."""
    return tuple(
        base_login(
            title_case(_FAKE_BY_LOGIN[emis].last_name),
            title_case(_FAKE_BY_LOGIN[emis].first_name),
        )
        for emis in EMIS_LOGINS
    )


async def demo_student_ids(container: Container) -> list[UUID]:
    """The user ids of the demo students who are registered."""
    directory = container.identity.directory
    ids: list[UUID] = []
    for login in demo_student_logins():
        user = await directory.user_by_login(login)
        if user is not None:
            ids.append(user.id)
    return ids


def _school_day(day: dt.date) -> dt.date:
    """The day itself, or the Monday after a weekend day."""
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return day


def _lesson_key(lesson: LessonRef, emis: int) -> int:
    """A number that is the same on every run for the same lesson."""
    return digest(lesson.date.isoformat(), lesson.period, emis)


async def _demo_file(container: Container, owner_id: UUID, name: str) -> UUID:
    """The teacher's file with this name, stored and processed once."""
    files = container.files.public
    for owned in await files.list_owned(owner_id, limit=200):
        if owned.name == name:
            return owned.id
    ref = await files.store_bytes(
        owner_id=owner_id,
        scope=FileScope.STAFF,
        purpose=FilePurpose.LINK,
        name=name,
        data=DEMO_FILES[name](),
    )
    await container.files.process_file.execute(ref.id)
    return ref.id


async def _attach(
    container: Container,
    lesson: LessonRef,
    teacher: Actor,
    role: Literal["material", "attachment"],
    name: str,
) -> bool:
    """Attach the named file to the lesson unless it is attached already."""
    refs = await container.links.public.lesson_resources(lesson.id, include_hidden=True)
    if any(ref.title == name and ref.role == role for ref in refs):
        return False
    file_id = await _demo_file(container, teacher.user_id, name)
    await container.links.public.add_lesson_resource(
        teacher, lesson.id, role=role, file_id=file_id
    )
    return True


async def _tick(
    container: Container,
    lesson: LessonRef,
    students: Sequence[UUID],
    key: int,
    *,
    monday: dt.date,
    today: dt.date,
) -> None:
    """Students tick their homework: last week mostly, this week sometimes."""
    classwork = container.academic.classwork
    for student_id in students:
        mark = digest(key, student_id)
        if lesson.date < monday:
            done = mark % 3 != 0  # a third of last week's stays open: overdue
        elif lesson.date <= today:
            done = mark % 4 == 0
        else:
            continue
        if done:
            actor = Actor(user_id=student_id, roles=frozenset({Role.STUDENT}))
            await classwork.set_homework_done.execute(lesson.id, actor, True)


async def _set_homework(
    container: Container,
    lesson: LessonRef,
    teacher: Actor,
    emis: int,
    key: int,
    *,
    monday: dt.date,
) -> None:
    """Write the homework of one lesson: a text from the bank, due on a school day."""
    texts = HOMEWORK_TEXTS[emis]
    offset = (1 if lesson.date < monday else 2) + key % 3
    due = _school_day(lesson.date + dt.timedelta(days=offset))
    text = texts[key % len(texts)]
    await container.academic.classwork.set_homework.execute(
        lesson.id, teacher, text, due
    )


async def _seed_lesson(
    container: Container,
    lesson: LessonRef,
    teacher: Actor,
    emis: int,
    attendees: Sequence[UUID],
    *,
    monday: dt.date,
    today: dt.date,
    material_done: set[tuple[int, tuple[str, ...]]],
) -> bool:
    """Homework, ticks, a homework file and a material for one lesson; True if new."""
    key = _lesson_key(lesson, emis)
    created = not lesson.homework_text and key % 10 < HOMEWORK_SHARE
    if created:
        await _set_homework(container, lesson, teacher, emis, key, monday=monday)
        await _tick(container, lesson, attendees, key, monday=monday, today=today)
    has_homework = bool(lesson.homework_text) or created
    if has_homework and emis in HOMEWORK_FILES and key % 3 == 0:
        await _attach(container, lesson, teacher, "attachment", HOMEWORK_FILES[emis])
    group = tuple(sorted(lesson.group_names))
    first_this_week = lesson.date >= monday and (emis, group) not in material_done
    if emis in MATERIALS and first_this_week:
        material_done.add((emis, group))
        await _attach(container, lesson, teacher, "material", MATERIALS[emis])
    return created


async def seed_homework(container: Container, student_ids: Sequence[UUID]) -> int:
    """Homework, files and ticks for the demo students' lessons; return the new ones.

    Lessons from last week to the end of next week are covered.
    """
    today = local_today(container.clock)
    monday = today - dt.timedelta(days=today.weekday())
    queries = container.academic.schedule.queries
    lessons: dict[UUID, LessonRef] = {}
    attendees: dict[UUID, list[UUID]] = {}
    for student_id in student_ids:
        found = await queries.lessons_for_student(
            student_id, monday - dt.timedelta(days=7), monday + dt.timedelta(days=13)
        )
        for lesson in found:
            lessons[lesson.id] = lesson
            attendees.setdefault(lesson.id, []).append(student_id)

    material_done: set[tuple[int, tuple[str, ...]]] = set()
    created = 0
    for lesson in sorted(lessons.values(), key=lambda item: (item.date, item.period)):
        emis = await queries.subject_emis_id(lesson.subject_id)
        if (
            emis is None
            or lesson.status != "scheduled"
            or lesson.teacher_id is None
            or lesson.kind in _NON_HOMEWORK_KINDS
        ):
            continue
        teacher = Actor(user_id=lesson.teacher_id, roles=frozenset({Role.TEACHER}))
        created += await _seed_lesson(
            container,
            lesson,
            teacher,
            emis,
            attendees.get(lesson.id, []),
            monday=monday,
            today=today,
            material_done=material_done,
        )
    log.info("seed_homework_done", created=created)
    return created
