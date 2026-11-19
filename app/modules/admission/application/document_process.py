"""The issuing process of application documents, with the student's own status."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.consultations import ProcessUnitOfWork

ProcessUowFactory = Callable[[], ProcessUnitOfWork]


@dataclass(frozen=True, slots=True)
class _Step:
    key: str
    lead_days: tuple[int, int]
    kind: str | None
    text: dict[str, tuple[str, str, str]]  # locale -> (title, issuer, description)


_STEPS: Final[tuple[_Step, ...]] = (
    _Step(
        "transcript",
        (3, 5),
        None,
        {
            "uz": (
                "Transkript",
                "Registrator (transkript xodimi)",
                "Rasmiy oʻquv transkripti. Talabni ilovada yuboring.",
            ),
            "ru": (
                "Транскрипт",
                "Регистратор (сотрудник по транскриптам)",
                "Официальный транскрипт успеваемости. "
                "Запрос отправляется в приложении.",
            ),
            "en": (
                "Transcript",
                "Registrar (transcript officer)",
                "The official academic transcript. Request it in the app.",
            ),
        },
    ),
    _Step(
        "school_profile",
        (5, 7),
        "school_report",
        {
            "uz": (
                "Maktab profili",
                "Maslahatchi",
                "Litsey haqida umumiy maʼlumot; qabul komissiyalari uchun.",
            ),
            "ru": (
                "Школьный профиль",
                "Консультант",
                "Описание лицея для приёмных комиссий.",
            ),
            "en": (
                "School profile",
                "Counselor",
                "A description of the lyceum for admission committees.",
            ),
        },
    ),
    _Step(
        "recommendations",
        (10, 14),
        "rec",
        {
            "uz": (
                "Tavsiya xatlari",
                "Oʻqituvchilar",
                "Oʻqituvchilardan 3-4 hafta oldin soʻrang.",
            ),
            "ru": (
                "Рекомендательные письма",
                "Учителя",
                "Просите учителей за 3-4 недели до срока.",
            ),
            "en": (
                "Recommendation letters",
                "Teachers",
                "Ask your teachers 3-4 weeks before the deadline.",
            ),
        },
    ),
    _Step(
        "counselor_letter",
        (10, 14),
        None,
        {
            "uz": (
                "Maslahatchi xati",
                "Maslahatchi",
                "Maslahatchi xatini yozish uchun u bilan uchrashuv belgilang.",
            ),
            "ru": (
                "Письмо консультанта",
                "Консультант",
                "Запишитесь на консультацию, чтобы консультант написал письмо.",
            ),
            "en": (
                "Counselor letter",
                "Counselor",
                "Book a consultation so the counselor can write the letter.",
            ),
        },
    ),
    _Step(
        "translations",
        (5, 10),
        "translation",
        {
            "uz": (
                "Tarjimalar",
                "Tarjima byurosi",
                "Hujjatlar talab qilinadigan tilga tarjima qilinadi.",
            ),
            "ru": (
                "Переводы",
                "Бюро переводов",
                "Документы переводятся на язык, который требует вуз.",
            ),
            "en": (
                "Translations",
                "Translation agency",
                "Documents are translated into the language the university asks for.",
            ),
        },
    ),
    _Step(
        "notarization",
        (1, 3),
        None,
        {
            "uz": (
                "Notarial tasdiqlash",
                "Notarius",
                "Nusxa yoki tarjima notarius tomonidan tasdiqlanadi.",
            ),
            "ru": (
                "Нотариальное заверение",
                "Нотариус",
                "Копии или переводы заверяет нотариус.",
            ),
            "en": (
                "Notarization",
                "Notary",
                "A notary certifies copies or translations.",
            ),
        },
    ),
)


@dataclass(frozen=True, slots=True)
class ProcessStep:
    """One step with its localized guidance and the student's status."""

    key: str
    title: str
    issuer: str
    description: str
    lead_days_min: int
    lead_days_max: int
    status: str  # not_started | requested | ready | in_review | not_tracked


class DocumentProcessService:
    """Explains who issues each document and where the student stands."""

    def __init__(self, uow_factory: ProcessUowFactory, access: AccessPolicy) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access

    async def steps(self, ctx: AdmissionContext, locale: str) -> list[ProcessStep]:
        """The steps in order, with the caller's own status for each."""
        student_id: UUID = ctx.user_id
        await self._access.require(ctx, student_id, Permission.DOCUMENTS_READ)
        async with self._uow() as uow:
            transcripts = await uow.transcripts.of_student(student_id)
            documents = await uow.documents.for_students([student_id])
        kinds = {d.kind for d in documents}
        out: list[ProcessStep] = []
        for s in _STEPS:
            title, issuer, desc = s.text.get(locale, s.text["en"])
            if s.key == "transcript":
                status = _transcript_status([t.status for t in transcripts])
            elif s.kind is None:
                status = "not_tracked"
            else:
                status = "ready" if s.kind in kinds else "not_started"
            out.append(ProcessStep(s.key, title, issuer, desc, *s.lead_days, status))
        return out


def _transcript_status(statuses: list[str]) -> str:
    for wanted in ("requested", "ready"):
        if wanted in statuses:
            return wanted
    return "not_started"
