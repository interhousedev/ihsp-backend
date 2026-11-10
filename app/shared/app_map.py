"""The map of app pages: where a feature lives, for the assistant, MCP and the web.

When you add a feature page to a web app (or a bot command), add it here too: the
assistant's `find_feature` tool, the MCP tool of the same name and `GET /v1/app-map`
all read this tuple, so a page that is missing here cannot be found by anyone.
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

from app.settings import UrlsSettings
from app.shared.actor import Role

AppName = Literal["sp", "staff", "admin", "lms", "library", "id", "bot"]
LOCALES: Final = ("uz", "ru", "en")
DEFAULT_LOCALE: Final = "en"


@dataclass(frozen=True, slots=True)
class Destination:
    """One page (or bot command): its app, path, who may open it and how to find it."""

    id: str
    app: AppName
    path: str
    roles: frozenset[Role]  # empty: every signed-in user
    title: dict[str, str]
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Found:
    """A destination with its absolute URL (None for bot commands)."""

    destination: Destination
    url: str | None


def _d(
    id_: str,
    app: AppName,
    path: str,
    roles: set[Role],
    titles: tuple[str, str, str],
    words: str,
) -> Destination:
    """Build a destination; `words` are space-separated keywords in all languages."""
    return Destination(
        id=id_,
        app=app,
        path=path,
        roles=frozenset(roles),
        title=dict(zip(LOCALES, titles, strict=True)),
        keywords=tuple(words.split()),
    )


_ST = {Role.STUDENT}
_TE = {Role.TEACHER}
_AD = {Role.ADMIN}
_LIBM = {Role.LIBRARIAN, Role.ADMIN}
_LMSA = {Role.LMS_ADMIN, Role.LMS_CREATOR}
_ALL: set[Role] = set()

APP_MAP: Final[tuple[Destination, ...]] = (
    # - - - Student app (sp) - - -
    _d(
        "sp-home",
        "sp",
        "/",
        _ST,
        ("Bosh sahifa", "Главная", "Home"),
        "bosh sahifa главная home dashboard bugun сегодня today",
    ),
    _d(
        "sp-timetable",
        "sp",
        "/timetable/",
        _ST,
        ("Dars jadvali", "Расписание и посещаемость", "Timetable and attendance"),
        "jadval dars расписание уроки timetable schedule calendar kalendar "
        "davomat посещаемость attendance",
    ),
    _d(
        "sp-subjects",
        "sp",
        "/subjects/",
        _ST,
        ("Fanlar", "Предметы", "Subjects"),
        "fanlar fan предметы предмет subjects subject",
    ),
    _d(
        "sp-grades",
        "sp",
        "/grades/",
        _ST,
        ("Baholar", "Оценки", "Grades"),
        "baholar baho оценки оценка отметки grades marks gpa журнал ПК ИК",
    ),
    _d(
        "sp-homework",
        "sp",
        "/homework/",
        _ST,
        ("Uy vazifalari", "Домашние задания", "Homework"),
        "uy vazifa vazifalari домашка домашнее задание homework assignment",
    ),
    _d(
        "sp-exams",
        "sp",
        "/exams/",
        _ST,
        ("Imtihonlar", "Экзамены", "Exams"),
        "imtihon imtihonlar экзамен экзамены exam exams test",
    ),
    _d(
        "sp-teachers",
        "sp",
        "/teachers/",
        _ST,
        ("O'qituvchilar", "Учителя", "Teachers"),
        "oqituvchi oqituvchilar ustoz учитель учителя преподаватели teacher teachers",
    ),
    _d(
        "sp-my-group",
        "sp",
        "/my-group/",
        _ST,
        ("Mening guruhim", "Моя группа", "My group"),
        "guruh guruhim группа староста classmates sinfdoshlar group head",
    ),
    _d(
        "sp-assistant",
        "sp",
        "/assistant/",
        _ST,
        ("AI yordamchi", "ИИ-ассистент", "AI assistant"),
        "yordamchi ai assistant ассистент ии чат chat sunʼiy intellekt",
    ),
    _d(
        "sp-notebooks",
        "sp",
        "/notebooks/",
        _ST,
        ("Daftarlar", "Блокноты", "Notebooks"),
        "daftar daftarlar блокнот блокноты notebook notebooks studio конспект",
    ),
    _d(
        "sp-flashcards",
        "sp",
        "/flashcards/",
        _ST,
        ("Kartochkalar", "Карточки", "Flash cards"),
        "kartochka kartochkalar карточки flashcards flash cards",
    ),
    _d(
        "sp-files",
        "sp",
        "/files/",
        _ST,
        ("Fayllar", "Файлы", "Files"),
        "fayl fayllar файлы файл files upload yuklash",
    ),
    _d(
        "sp-links",
        "sp",
        "/links/",
        _ST,
        ("Havolalar", "Ссылки", "Links"),
        "havola havolalar ссылки ссылка links link short qisqa",
    ),
    _d(
        "sp-notifications",
        "sp",
        "/notifications/",
        _ST,
        ("Bildirishnomalar", "Уведомления", "Notifications"),
        "bildirishnoma bildirishnomalar уведомления notifications push",
    ),
    _d(
        "sp-mail",
        "sp",
        "/mail/",
        _ST,
        ("Pochta", "Почта", "Mail"),
        "pochta xat почта письмо письма mail email inbox",
    ),
    _d(
        "sp-settings",
        "sp",
        "/settings/",
        _ST,
        ("Sozlamalar", "Настройки", "Settings"),
        "sozlamalar sozlama настройки settings til язык language",
    ),
    _d(
        "sp-excuses",
        "sp",
        "/excuses/",
        _ST,
        ("Sababli yo'qlik", "Справки об отсутствии", "Absence excuses"),
        "sabab sababli yoqlik spravka справка пропуск отсутствие болезнь excuse "
        "excuses absence sick note",
    ),
    _d(
        "sp-face",
        "sp",
        "/profile/face/",
        _ST,
        ("Yuz bilan kirish", "Вход по лицу", "Face sign-in"),
        "yuz face лицо faceid face-id biometric biometriya",
    ),
    _d(
        "sp-account",
        "sp",
        "/profile/account/",
        _ST,
        ("Hisob (iht.id)", "Аккаунт (iht.id)", "Account (iht.id)"),
        "hisob akkaunt аккаунт account profile profil профиль",
    ),
    # - - - Staff app - - -
    _d(
        "staff-home",
        "staff",
        "/",
        _TE,
        ("Bugun", "Сегодня", "Today"),
        "bugun сегодня today bosh главная home",
    ),
    _d(
        "staff-timetable",
        "staff",
        "/timetable/",
        _TE,
        ("Dars jadvali", "Расписание", "Timetable"),
        "jadval dars расписание уроки timetable schedule",
    ),
    _d(
        "staff-journal",
        "staff",
        "/journal/",
        _TE,
        ("Jurnal", "Журнал", "Journal"),
        "jurnal журнал journal baho оценки grades marks davomat attendance",
    ),
    _d(
        "staff-subjects",
        "staff",
        "/subjects/",
        _TE,
        ("Fanlar", "Предметы", "Subjects"),
        "fanlar fan предметы предмет subjects",
    ),
    _d(
        "staff-temporary-marks",
        "staff",
        "/temporary-marks/",
        _TE,
        ("Vaqtinchalik baholar", "Временные оценки", "Temporary marks"),
        "vaqtinchalik временные оценки temporary marks baho",
    ),
    _d(
        "staff-students",
        "staff",
        "/students/",
        _TE,
        ("O'quvchilarni qidirish", "Поиск учеников", "Student search"),
        "oquvchi oquvchilar ученик ученики студенты student students search "
        "qidiruv поиск",
    ),
    _d(
        "staff-notebooks",
        "staff",
        "/notebooks/",
        _TE,
        ("Daftarlar", "Блокноты", "Notebooks"),
        "daftar блокнот блокноты notebook notebooks studio",
    ),
    _d(
        "staff-group-exams",
        "staff",
        "/group/exams/",
        _TE,
        ("Guruh imtihonlari", "Экзамены группы", "Group exams"),
        "imtihon imtihonlar экзамен экзамены exam exams guruh группа",
    ),
    _d(
        "staff-group",
        "staff",
        "/group/",
        _TE,
        ("Guruhim", "Моя группа", "My group"),
        "guruh guruhim группа куратор curator group kurator",
    ),
    _d(
        "staff-subgroups",
        "staff",
        "/group/subgroups/",
        _TE,
        ("Kichik guruhlar", "Подгруппы", "Subgroups"),
        "kichik guruh подгруппа подгруппы subgroup subgroups",
    ),
    _d(
        "staff-group-attendance",
        "staff",
        "/group/attendance/",
        _TE,
        ("Guruh davomati", "Посещаемость группы", "Group attendance"),
        "davomat посещаемость attendance guruh группа",
    ),
    _d(
        "staff-certificates",
        "staff",
        "/certificates/",
        _TE,
        ("Ma'lumotnomalar", "Справки", "Certificates"),
        "malumotnoma spravka справка справки certificate certificates",
    ),
    _d(
        "staff-notifications",
        "staff",
        "/notifications/",
        _TE,
        ("Bildirishnomalar", "Уведомления", "Notifications"),
        "bildirishnoma уведомления notifications push",
    ),
    _d(
        "staff-mail",
        "staff",
        "/mail/",
        _TE,
        ("Pochta", "Почта", "Mail"),
        "pochta xat почта письмо mail email inbox",
    ),
    _d(
        "staff-settings",
        "staff",
        "/settings/",
        _TE,
        ("Sozlamalar", "Настройки", "Settings"),
        "sozlamalar настройки settings til язык language",
    ),
    _d(
        "staff-excuses",
        "staff",
        "/excuses/",
        _TE,
        ("Sababli yo'qlik", "Справки об отсутствии", "Absence excuses"),
        "sabab sababli yoqlik spravka справка пропуск отсутствие excuse excuses "
        "absence sick note",
    ),
    # - - - Admin app - - -
    _d(
        "admin-home",
        "admin",
        "/",
        _AD,
        ("Bosh sahifa", "Главная", "Home"),
        "bosh главная home dashboard",
    ),
    _d(
        "admin-students",
        "admin",
        "/students/",
        _AD,
        ("O'quvchilar", "Ученики", "Students"),
        "oquvchi oquvchilar ученик ученики student students",
    ),
    _d(
        "admin-teachers",
        "admin",
        "/teachers/",
        _AD,
        ("O'qituvchilar", "Учителя", "Teachers"),
        "oqituvchi ustoz учитель учителя teacher teachers",
    ),
    _d(
        "admin-users",
        "admin",
        "/users/",
        _AD,
        ("Foydalanuvchilar", "Пользователи", "Users"),
        "foydalanuvchi foydalanuvchilar пользователь пользователи user users role "
        "rol роль block блокировка",
    ),
    _d(
        "admin-login-cues",
        "admin",
        "/login-cues/",
        _AD,
        ("Kirish kodlari", "Коды входа", "Login cues"),
        "kirish kod коды вход login cue cues",
    ),
    _d(
        "admin-groups",
        "admin",
        "/groups/",
        _AD,
        ("Guruhlar", "Группы", "Groups"),
        "guruh guruhlar группа группы group groups",
    ),
    _d(
        "admin-subjects",
        "admin",
        "/subjects/",
        _AD,
        ("Fanlar", "Предметы", "Subjects"),
        "fanlar fan предметы предмет subjects",
    ),
    _d(
        "admin-rooms",
        "admin",
        "/rooms/",
        _AD,
        ("Xonalar", "Кабинеты", "Rooms"),
        "xona xonalar кабинет кабинеты аудитории room rooms",
    ),
    _d(
        "admin-terms",
        "admin",
        "/terms/",
        _AD,
        ("Choraklar", "Периоды", "Terms"),
        "chorak choraklar период периоды четверть term terms semester",
    ),
    _d(
        "admin-timetable",
        "admin",
        "/timetable/",
        _AD,
        ("Dars jadvali", "Расписание", "Timetable"),
        "jadval dars расписание timetable schedule",
    ),
    _d(
        "admin-lessons",
        "admin",
        "/lessons/",
        _AD,
        ("Darslar", "Уроки", "Lessons"),
        "dars darslar урок уроки lesson lessons",
    ),
    _d(
        "admin-exams",
        "admin",
        "/exams/",
        _AD,
        ("Imtihonlar", "Экзамены", "Exams"),
        "imtihon imtihonlar экзамен экзамены exam exams",
    ),
    _d(
        "admin-knowledge",
        "admin",
        "/knowledge/",
        _AD,
        ("Bilimlar bazasi", "База знаний", "Knowledge base"),
        "bilim bilimlar baza база знаний knowledge base faq",
    ),
    _d(
        "admin-attendance",
        "admin",
        "/attendance/",
        _AD,
        ("Davomat", "Посещаемость", "Attendance"),
        "davomat посещаемость attendance",
    ),
    _d(
        "admin-work-offs",
        "admin",
        "/work-offs/",
        _AD,
        ("Otrabotkalar", "Отработки", "Work-offs"),
        "otrabotka otrabotkalar отработка отработки work-off workoff work-offs",
    ),
    _d(
        "admin-reports",
        "admin",
        "/reports/",
        _AD,
        ("Hisobotlar", "Отчёты", "Reports"),
        "hisobot hisobotlar отчёт отчеты отчет report reports export",
    ),
    _d(
        "admin-certificates",
        "admin",
        "/certificates/",
        _AD,
        ("Ma'lumotnomalar", "Справки", "Certificates"),
        "malumotnoma spravka справка справки certificate certificates",
    ),
    _d(
        "admin-certificate-types",
        "admin",
        "/certificate-types/",
        _AD,
        ("Ma'lumotnoma turlari", "Типы справок", "Certificate types"),
        "tur turlari типы справок certificate types",
    ),
    _d(
        "admin-monitoring",
        "admin",
        "/monitoring/",
        _AD,
        ("Monitoring", "Мониторинг", "Monitoring"),
        "monitoring мониторинг health jobs sync синхронизация",
    ),
    _d(
        "admin-logs",
        "admin",
        "/logs/",
        _AD,
        ("Jurnallar", "Логи", "Logs"),
        "log loglar логи журнал ошибок logs errors",
    ),
    _d(
        "admin-mcp-activity",
        "admin",
        "/mcp-activity/",
        _AD,
        ("MCP faolligi", "Активность MCP", "MCP activity"),
        "mcp faollik активность activity connectors",
    ),
    _d(
        "admin-limits",
        "admin",
        "/limits/",
        _AD,
        ("Limitlar va foydalanish", "Лимиты и использование", "Limits & usage"),
        "limit limitlar лимиты использование usage ai quota kvota",
    ),
    _d(
        "admin-broadcasts",
        "admin",
        "/broadcasts/",
        _AD,
        ("E'lonlar", "Рассылки", "Broadcasts"),
        "elon elonlar рассылка рассылки объявление broadcast broadcasts announcement",
    ),
    _d(
        "admin-bot-posts",
        "admin",
        "/bot-posts/",
        _AD,
        ("Bot postlari", "Посты бота", "Bot posts"),
        "post postlar bot посты бота bot-posts channel kanal",
    ),
    _d(
        "admin-moderation",
        "admin",
        "/moderation/",
        _AD,
        ("Moderatsiya", "Модерация", "Moderation"),
        "moderatsiya модерация moderation report shikoyat жалоба",
    ),
    _d(
        "admin-call-for-improvements",
        "admin",
        "/call-for-improvements/",
        _AD,
        ("Takliflar", "Предложения", "Call for improvements"),
        "taklif takliflar предложения отзывы feedback improvements ideas",
    ),
    _d(
        "admin-assistant",
        "admin",
        "/assistant/",
        _AD,
        ("AI yordamchi", "ИИ-ассистент", "AI assistant"),
        "yordamchi ai assistant ассистент ии chat чат",
    ),
    _d(
        "admin-settings",
        "admin",
        "/settings/",
        _AD,
        ("Sozlamalar", "Настройки", "Settings"),
        "sozlamalar настройки settings",
    ),
    _d(
        "admin-excuses",
        "admin",
        "/excuses/",
        _AD,
        ("Sababli yo'qlik", "Справки об отсутствии", "Absence excuses"),
        "sabab sababli yoqlik spravka справка пропуск отсутствие excuse excuses "
        "absence sick note",
    ),
    _d(
        "admin-vault",
        "admin",
        "/vault/",
        _AD,
        ("Seyf", "Хранилище секретов", "Vault"),
        "seyf vault хранилище секреты secrets keys kalit unseal",
    ),
    _d(
        "admin-devices",
        "admin",
        "/devices/",
        _AD,
        ("Qurilmalar", "Устройства", "Devices"),
        "qurilma qurilmalar устройства device devices terminal kiosk face yuz",
    ),
    # - - - Sign-in app (id) - - -
    _d(
        "id-security",
        "id",
        "/security/",
        _ALL,
        ("Xavfsizlik", "Безопасность", "Security"),
        "xavfsizlik безопасность security account hisob аккаунт",
    ),
    _d(
        "id-password",
        "id",
        "/security/password/",
        _ALL,
        ("Parol", "Пароль", "Password"),
        "parol пароль password change almashtirish сменить",
    ),
    _d(
        "id-otp",
        "id",
        "/security/otp/",
        _ALL,
        ("Ikki bosqichli tekshiruv", "Двухфакторная защита", "Two-factor (OTP)"),
        "otp 2fa ikki bosqichli двухфакторная authenticator autentifikator two-factor",
    ),
    _d(
        "id-telegram",
        "id",
        "/security/telegram/",
        _ALL,
        ("Telegram", "Telegram", "Telegram"),
        "telegram bot ulash привязать подключить link connect",
    ),
    _d(
        "id-email",
        "id",
        "/security/email/",
        _ALL,
        ("Elektron pochta", "Электронная почта", "Email"),
        "email pochta почта эл адрес e-mail address",
    ),
    _d(
        "id-sessions",
        "id",
        "/security/sessions/",
        _ALL,
        ("Seanslar", "Сессии", "Sessions"),
        "seans seanslar сессии сессия sessions devices qurilmalar logout chiqish выйти",
    ),
    _d(
        "id-activity",
        "id",
        "/security/activity/",
        _ALL,
        ("Faollik", "Активность", "Activity"),
        "faollik активность activity history tarix история log",
    ),
    _d(
        "id-emis",
        "id",
        "/security/emis/",
        _ST,
        ("EMIS", "EMIS", "EMIS"),
        "emis hemis ulash привязка link connect",
    ),
    _d(
        "id-delete",
        "id",
        "/security/delete/",
        _ST,
        ("Hisobni o'chirish", "Удаление аккаунта", "Delete account"),
        "ochirish удалить удаление delete account hisob",
    ),
    _d(
        "id-connectors",
        "id",
        "/connectors/",
        _ALL,
        ("AI ulagichlar (MCP)", "ИИ-коннекторы (MCP)", "AI connectors (MCP)"),
        "ulagich mcp коннектор коннекторы claude chatgpt connector connectors ai ии",
    ),
    _d(
        "id-appearance",
        "id",
        "/appearance/",
        _ALL,
        ("Ko'rinish", "Оформление", "Appearance"),
        "korinish оформление appearance theme tema тема dark qorongi темная",
    ),
    _d(
        "id-personal-tokens",
        "id",
        "/personal-tokens/",
        _ALL,
        ("Shaxsiy tokenlar", "Личные токены", "Personal tokens"),
        "token tokenlar токен токены personal shaxsiy личные api key kalit",
    ),
    # - - - Library - - -
    _d(
        "library-home",
        "library",
        "/",
        _ALL,
        ("Kutubxona", "Библиотека", "Library"),
        "kutubxona библиотека library books kitob kitoblar книги",
    ),
    _d(
        "library-browse",
        "library",
        "/browse/",
        _ALL,
        ("Katalog", "Каталог", "Browse"),
        "katalog каталог browse search qidiruv поиск books kitob книги",
    ),
    _d(
        "library-my",
        "library",
        "/my/",
        _ALL,
        ("Mening kitoblarim", "Мои книги", "My books"),
        "mening kitoblarim мои книги my books reading o'qish чтение",
    ),
    _d(
        "library-lists",
        "library",
        "/lists/",
        _ALL,
        ("Ro'yxatlar", "Списки", "Lists"),
        "royxat royxatlar списки список lists reading shelf",
    ),
    _d(
        "library-upload",
        "library",
        "/upload/",
        _ALL,
        ("Kitob yuklash", "Загрузить книгу", "Upload a book"),
        "yuklash kitob загрузить книгу upload book pdf",
    ),
    _d(
        "library-queue",
        "library",
        "/manage/queue/",
        _LIBM,
        ("Navbat", "Очередь", "Queue"),
        "navbat очередь queue moderation moderatsiya",
    ),
    _d(
        "library-books",
        "library",
        "/manage/books/",
        _LIBM,
        ("Kitoblar", "Книги", "Books"),
        "kitoblar книги books manage",
    ),
    _d(
        "library-topics",
        "library",
        "/manage/topics/",
        _LIBM,
        ("Mavzular", "Темы", "Topics"),
        "mavzu mavzular темы тема topics",
    ),
    _d(
        "library-subjects",
        "library",
        "/manage/subjects/",
        _LIBM,
        ("Fanlar", "Предметы", "Subjects"),
        "fanlar fan предметы subjects",
    ),
    _d(
        "library-collections",
        "library",
        "/manage/collections/",
        _LIBM,
        ("To'plamlar", "Подборки", "Collections"),
        "toplam toplamlar подборки коллекции collections",
    ),
    _d(
        "library-stats",
        "library",
        "/manage/stats/",
        _LIBM,
        ("Statistika", "Статистика", "Statistics"),
        "statistika статистика stats statistics",
    ),
    _d(
        "library-unilibrary",
        "library",
        "/manage/unilibrary/",
        _AD,
        ("UniLibrary", "UniLibrary", "UniLibrary"),
        "unilibrary uni library",
    ),
    # - - - LMS - - -
    _d(
        "lms-catalog",
        "lms",
        "/",
        _ALL,
        ("Kurslar", "Каталог курсов", "Course catalog"),
        "kurs kurslar курс курсы courses course catalog lms o'quv",
    ),
    _d(
        "lms-my",
        "lms",
        "/my/",
        _ALL,
        ("Mening kurslarim", "Мои курсы", "My courses"),
        "mening kurslarim мои курсы my courses progress progress прогресс",
    ),
    _d(
        "lms-notebooks",
        "lms",
        "/notebooks/",
        _ALL,
        ("Daftarlar", "Блокноты", "Notebooks"),
        "daftar блокнот блокноты notebook notebooks studio",
    ),
    _d(
        "lms-join",
        "lms",
        "/join/",
        _ALL,
        ("Kursga qo'shilish", "Вступить в курс", "Join a course"),
        "qoshilish вступить код join code kurs курс invite",
    ),
    _d(
        "lms-admin",
        "lms",
        "/admin/",
        _LMSA,
        ("Kurslarni boshqarish", "Управление курсами", "Course authoring"),
        "boshqarish управление авторинг author authoring create yaratish создать "
        "course курс h5p",
    ),
    # - - - Telegram bot commands (no URL) - - -
    _d(
        "bot-today",
        "bot",
        "/today",
        _ST | _TE,
        ("Bugun", "Сегодня", "Today"),
        "bugun сегодня today lessons darslar уроки telegram bot",
    ),
    _d(
        "bot-marks",
        "bot",
        "/marks",
        _ST,
        ("Baholar", "Оценки", "Marks"),
        "baholar оценки marks grades telegram bot",
    ),
    _d(
        "bot-homework",
        "bot",
        "/homework",
        _ST,
        ("Uy vazifalari", "Домашние задания", "Homework"),
        "uy vazifa домашка homework telegram bot",
    ),
    _d(
        "bot-settings",
        "bot",
        "/settings",
        _ALL,
        ("Bot sozlamalari", "Настройки бота", "Bot settings"),
        "sozlamalar настройки settings notifications til язык language telegram bot",
    ),
    _d(
        "bot-feedback",
        "bot",
        "/feedback",
        _ALL,
        ("Fikr bildirish", "Обратная связь", "Feedback"),
        "fikr taklif обратная связь отзыв feedback bug telegram bot",
    ),
)

_WORD = re.compile(r"[\w'ʼ-]+", re.UNICODE)


def _normal(text: str) -> str:
    """Lower-case, with every apostrophe and the Russian ё folded away."""
    return text.lower().replace("ʼ", "").replace("'", "").replace("ё", "е")


def _tokens(text: str) -> list[str]:
    """Words of a query, normalised."""
    return [t for t in (_normal(w) for w in _WORD.findall(text)) if len(t) > 1]


def _origin(urls: UrlsSettings, app: AppName) -> str | None:
    """Origin of an app (None for the bot)."""
    if app == "bot":
        return None
    return str(getattr(urls, app)).rstrip("/")


def resolve(destination: Destination, urls: UrlsSettings) -> Found:
    """Attach the absolute URL of the destination."""
    origin = _origin(urls, destination.app)
    url = None if origin is None else origin + destination.path
    return Found(destination, url)


def visible_to(destination: Destination, roles: frozenset[Role]) -> bool:
    """True when the user may open the page (an empty role set means everyone)."""
    return not destination.roles or bool(destination.roles & roles)


def for_roles(urls: UrlsSettings, roles: frozenset[Role]) -> list[Found]:
    """Every destination the roles may open, in map order."""
    return [resolve(d, urls) for d in APP_MAP if visible_to(d, roles)]


def _score(destination: Destination, query: str, tokens: list[str], locale: str) -> int:
    """Relevance of a destination; 0 means no match."""
    title = _normal(destination.title.get(locale, destination.title[DEFAULT_LOCALE]))
    any_title = " ".join(_normal(t) for t in destination.title.values())
    words = [_normal(k) for k in destination.keywords]
    score = 0
    if query and query in title:
        score += 20
    for token in tokens:
        if token in title.split():
            score += 10
        elif token in title:
            score += 6
        if token in words:
            score += 8
        elif any(
            w.startswith(token) or token.startswith(w) for w in words if len(w) > 3
        ):
            score += 4
        if token in any_title:
            score += 2
    return score


def search(
    query: str,
    locale: str,
    roles: frozenset[Role],
    urls: UrlsSettings,
    limit: int = 5,
) -> list[Found]:
    """Pages that fit the query, best first; only pages the roles may open."""
    normal = _normal(query).strip()
    tokens = _tokens(query)
    scored = [
        (_score(d, normal, tokens, locale), index, d)
        for index, d in enumerate(APP_MAP)
        if visible_to(d, roles)
    ]
    ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))
    return [resolve(d, urls) for _, _, d in ranked[:limit]]
