"""The admission assistant: threads, messages, replies and starter questions."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

MESSAGE_MAX: Final = 2000
SCREEN_PATH_MAX: Final = 300
SCREEN_TITLE_MAX: Final = 200
SCREEN_SUMMARY_MAX: Final = 6000
TITLE_MAX: Final = 80
MAX_ROUNDS: Final = 4
"""Most model requests in one turn; the last one runs without tools."""
HISTORY_TURNS: Final = 12
"""Most earlier messages of the thread sent to the model."""
THREADS_MAX: Final = 50

Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class Screen:
    """What the student's page showed when they asked (untrusted text)."""

    path: str
    title: str
    summary: str


@dataclass(frozen=True, slots=True)
class Citation:
    """A record of the student's data an answer relied on."""

    source: str
    title: str
    url_path: str


@dataclass(frozen=True, slots=True)
class Action:
    """A button the answer offers: open a page or propose a task (nothing is made)."""

    kind: Literal["open", "propose_task"]
    label: str
    url_path: str | None = None
    task: dict[str, Any] | None = None


@dataclass(slots=True)
class Message:
    """One message of a thread."""

    id: UUID
    thread_id: UUID
    role: Role
    text: str
    created_at: dt.datetime
    citations: list[Citation] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)


@dataclass(slots=True)
class Thread:
    """A conversation of one student."""

    id: UUID
    student_id: UUID
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True, slots=True)
class Reply:
    """The assistant's answer to one message."""

    thread_id: UUID
    message_id: UUID
    text: str
    citations: list[Citation]
    actions: list[Action]


_T = tuple[str, str, str]  # uz, ru, en

_STARTERS: Final[dict[str, list[_T]]] = {
    "/": [
        (
            "Hozir eng muhim keyingi qadamim nima?",
            "Какой мой самый важный следующий шаг сейчас?",
            "What is my most important next step right now?",
        ),
        (
            "Yaqin muddatlarim qaysilar?",
            "Какие у меня ближайшие дедлайны?",
            "What are my upcoming deadlines?",
        ),
        (
            "Arizam qanchalik tayyor?",
            "Насколько готова моя заявка?",
            "How ready is my application?",
        ),
    ],
    "/setup": [
        (
            "Profilimning qaysi qismlari to‘ldirilmagan?",
            "Какие части моего профиля не заполнены?",
            "Which parts of my profile are still empty?",
        ),
        (
            "Uch so‘zim nimani anglatadi?",
            "Что значат мои три слова?",
            "What do my three words say about me?",
        ),
        (
            "Profilimni qanday yaxshilayman?",
            "Как улучшить мой профиль?",
            "How can I improve my profile?",
        ),
    ],
    "/activities": [
        (
            "Qaysi faoliyatim eng kuchli?",
            "Какое из моих достижений самое сильное?",
            "Which of my activities is the strongest?",
        ),
        (
            "Qaysi faoliyatlarni yaxshilash kerak?",
            "Какие записи стоит доработать?",
            "Which entries should I improve?",
        ),
        (
            "Yangi faoliyat g‘oyalari bormi?",
            "Какие новые активности мне подойдут?",
            "What new activities would suit me?",
        ),
    ],
    "/plan": [
        (
            "Bu oy nimalarga e’tibor berishim kerak?",
            "На чём мне сосредоточиться в этом месяце?",
            "What should I focus on this month?",
        ),
        (
            "Rejamdagi muddatlar to‘qnashmayaptimi?",
            "Не пересекаются ли дедлайны в моём плане?",
            "Do any deadlines in my plan collide?",
        ),
        (
            "Qaysi vazifalarni birinchi bajaray?",
            "Какие задачи сделать в первую очередь?",
            "Which tasks should I do first?",
        ),
    ],
    "/chooser": [
        (
            "Ro‘yxatim muvozanatlimi?",
            "Сбалансирован ли мой список университетов?",
            "Is my university list balanced?",
        ),
        (
            "Qaysi universitetlarning muddati yaqin?",
            "У каких университетов скоро дедлайн?",
            "Which universities have a deadline soon?",
        ),
        (
            "Test ballarim qaysi universitetlarga mos?",
            "Для каких университетов подходят мои баллы?",
            "Which universities fit my test scores?",
        ),
    ],
    "/essays": [
        (
            "Insholarim holati qanday?",
            "Что с моими эссе?",
            "Where do my essays stand?",
        ),
        (
            "Qaysi inshodan boshlashim kerak?",
            "С какого эссе мне начать?",
            "Which essay should I start with?",
        ),
        (
            "Insho uchun mavzu g‘oyalari bormi?",
            "Есть ли идеи тем для эссе?",
            "Do you have topic ideas for my essay?",
        ),
    ],
    "/documents": [
        (
            "Qaysi hujjatlar yetishmayapti?",
            "Каких документов мне не хватает?",
            "Which documents am I missing?",
        ),
        (
            "Qanday hujjatlar kerak bo‘ladi?",
            "Какие документы мне понадобятся?",
            "Which documents will I need?",
        ),
        (
            "Transkriptni qanday olaman?",
            "Как получить транскрипт?",
            "How do I get a transcript?",
        ),
    ],
    "/review": [
        (
            "Sharhning asosiy xulosasi nima?",
            "Каковы главные выводы обзора?",
            "What are the main findings of the review?",
        ),
        (
            "Eng zaif tomonim nima?",
            "Какая у меня самая слабая сторона?",
            "What is my weakest area?",
        ),
        (
            "Avval nimani tuzatay?",
            "Что исправить в первую очередь?",
            "What should I fix first?",
        ),
    ],
    "/career": [
        (
            "Qaysi yo‘nalishlar menga mos?",
            "Какие направления мне подходят?",
            "Which majors fit me?",
        ),
        (
            "Mening kuchli tomonim nima?",
            "В чём моя сильная сторона?",
            "What is my spike?",
        ),
        (
            "Qiziqishlarim nimaga olib keladi?",
            "К чему ведут мои интересы?",
            "Where do my interests lead?",
        ),
    ],
    "/opportunities": [
        (
            "Menga qaysi imkoniyatlar mos?",
            "Какие возможности мне подходят?",
            "Which opportunities fit me?",
        ),
        (
            "Qaysi imkoniyatning muddati yaqin?",
            "У какой возможности скоро дедлайн?",
            "Which opportunity closes soon?",
        ),
        (
            "Rejaga nimani qo‘shay?",
            "Что добавить в мой план?",
            "What should I add to my plan?",
        ),
    ],
    "/courses": [
        (
            "Baholarim qanday?",
            "Какие у меня оценки?",
            "How are my grades?",
        ),
        (
            "Qaysi fanlarni kuchaytirish kerak?",
            "Какие предметы стоит подтянуть?",
            "Which subjects should I strengthen?",
        ),
        (
            "Kurslarim arizamga qanday ta’sir qiladi?",
            "Как мои курсы влияют на заявку?",
            "How do my courses affect my application?",
        ),
    ],
    "/tasks": [
        (
            "Qaysi vazifalarning muddati o‘tib ketgan?",
            "Какие задачи просрочены?",
            "Which tasks are overdue?",
        ),
        (
            "Bugun nimani bajarishim kerak?",
            "Что мне сделать сегодня?",
            "What should I do today?",
        ),
        (
            "Menga yangi vazifalar taklif qil",
            "Предложи мне новые задачи",
            "Suggest new tasks for me",
        ),
    ],
}

_DEFAULT: Final = _STARTERS["/"]
_LOCALES: Final = {"uz": 0, "ru": 1, "en": 2}


def starter_questions(path: str, locale: str) -> list[str]:
    """Three starter questions of the screen at `path` (longest matching prefix)."""
    clean = "/" + path.split("?", 1)[0].strip("/")
    best = ""
    for prefix in _STARTERS:
        if prefix != "/" and (clean == prefix or clean.startswith(prefix + "/")):
            best = max(best, prefix, key=len)
    rows = _STARTERS.get(best or clean, _DEFAULT)
    index = _LOCALES.get(locale, 2)
    return [row[index] for row in rows]
