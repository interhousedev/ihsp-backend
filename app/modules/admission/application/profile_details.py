"""Use cases of profile details: interests, quiz answers and completion."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.profile_details import (
    QUIZZES,
    AnswerValue,
    Completion,
    Interests,
    QuizAnswers,
    clean_answers,
    clean_interests,
    completion,
)
from app.modules.admission.ports.consultations import DetailsUnitOfWork
from app.shared.clock import Clock

DetailsUowFactory = Callable[[], DetailsUnitOfWork]

_MISSING: Final[dict[str, dict[str, str]]] = {
    "setup": {
        "uz": "Profil sozlamasini yakunlang",
        "ru": "Завершите настройку профиля",
        "en": "Finish the profile setup",
    },
    "three_words": {
        "uz": "O'zingizni tasvirlovchi uchta so'zni tanlang",
        "ru": "Выберите три слова о себе",
        "en": "Choose three words about yourself",
    },
    "interest_fields": {
        "uz": "Qiziqish sohalarini belgilang",
        "ru": "Отметьте области интересов",
        "en": "Pick your fields of interest",
    },
    "service_interests": {
        "uz": "Ijtimoiy faoliyat yo'nalishlarini belgilang",
        "ru": "Отметьте направления служения обществу",
        "en": "Pick your service interests",
    },
    "career_quiz": {
        "uz": "Kollej testini yakunlang",
        "ru": "Пройдите тест подбора колледжа",
        "en": "Complete the college quiz",
    },
    "algorithm_quiz": {
        "uz": "Algoritm testini yakunlang",
        "ru": "Пройдите тест алгоритма",
        "en": "Complete the algorithm quiz",
    },
    "activities": {
        "uz": "Kamida bitta faoliyat qo'shing",
        "ru": "Добавьте хотя бы одну активность",
        "en": "Add at least one activity",
    },
}


@dataclass(frozen=True, slots=True)
class MissingDetail:
    """A missing profile detail with its localized label."""

    key: str
    label: str


@dataclass(frozen=True, slots=True)
class DetailsOverview:
    """Interests, the three words and how complete the profile is."""

    interests: Interests
    three_words: tuple[str, ...]
    percent: int
    missing: tuple[MissingDetail, ...]


def missing_details(done: Completion, locale: str) -> tuple[MissingDetail, ...]:
    """Localize the missing keys (unknown locale falls back to English)."""
    return tuple(
        MissingDetail(k, _MISSING[k].get(locale, _MISSING[k]["en"]))
        for k in done.missing
    )


class ProfileDetailsService:
    """Interests, quiz answers and completion of the student's own profile."""

    def __init__(
        self, uow_factory: DetailsUowFactory, access: AccessPolicy, clock: Clock
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock

    async def _own(self, ctx: AdmissionContext) -> UUID:
        await self._access.require(ctx, ctx.user_id, Permission.PROFILE_READ)
        return ctx.user_id

    async def overview(self, ctx: AdmissionContext, locale: str) -> DetailsOverview:
        """Interests, words, completion percent and the missing list."""
        student_id = await self._own(ctx)
        async with self._uow() as uow:
            profile = await uow.profiles.get(student_id)
            words = await uow.profiles.get_words(student_id)
            interests = await uow.profile_details.get_interests(student_id)
            quizzes = await uow.profile_details.completed_quizzes(student_id)
            items = await uow.items.list_for(student_id)
        three = words.words if words else ()
        done = completion(
            setup_done=bool(profile and profile.setup_completed_at),
            has_words=bool(three),
            interests=interests,
            quizzes_done=quizzes,
            has_activity=bool(items),
        )
        return DetailsOverview(
            interests, three, done.percent, missing_details(done, locale)
        )

    async def put_interests(
        self, ctx: AdmissionContext, fields: list[str], services: list[str]
    ) -> Interests:
        """Replace the fields of interest and the service interests."""
        student_id = await self._own(ctx)
        interests = clean_interests(fields, services)
        async with self._uow() as uow:
            await uow.profile_details.save_interests(
                student_id, interests, self._clock.now()
            )
            await uow.commit()
        return interests

    async def get_quiz(self, ctx: AdmissionContext, quiz: str) -> QuizAnswers:
        """The stored answers of a quiz (empty when none)."""
        student_id = await self._own(ctx)
        if quiz not in QUIZZES:
            raise AdmissionNotFoundError()
        async with self._uow() as uow:
            found = await uow.profile_details.get_quiz(student_id, quiz)
        return found or QuizAnswers(student_id, quiz, {}, False)

    async def put_quiz(
        self,
        ctx: AdmissionContext,
        quiz: str,
        answers: Mapping[str, object],
        completed: bool,
    ) -> QuizAnswers:
        """Replace the answers of a quiz."""
        student_id = await self._own(ctx)
        if quiz not in QUIZZES:
            raise AdmissionNotFoundError()
        clean: dict[str, AnswerValue] = clean_answers(answers)
        stored = QuizAnswers(student_id, quiz, clean, completed)
        async with self._uow() as uow:
            await uow.profile_details.save_quiz(stored, self._clock.now())
            await uow.commit()
        return stored
