"""The map of app pages: where a feature lives, for the assistant, MCP and the web.

When you add a feature page to a web app (or a bot command), add it here too: the
assistant's `find_feature` tool, the MCP tool of the same name and `GET /v1/app-map`
all read this tuple, so a page that is missing here cannot be found by anyone.
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

from app.settings import UrlsSettings
from app.settings_features import FeaturesSettings
from app.shared.actor import Role

AppName = Literal["sp", "staff", "admin", "lms", "library", "id", "bot", "admission"]
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
_ADM = {Role.COUNSELOR, Role.MENTOR, Role.ADMIN}
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
        "sp-honours",
        "sp",
        "/honours/",
        _ST,
        (
            "Qizil diplom va medallar",
            "Красный диплом и медали",
            "Red diploma and medals",
        ),
        "qizil diplom medal oltin kumush красный диплом медаль золотая серебряная "
        "аттестат reyting kitobi рейтинг-книжка red diploma gold silver medal "
        "rating book honours",
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
        ("Oʻqituvchilar", "Учителя", "Teachers"),
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
        "sp-rating",
        "sp",
        "/rating/",
        _ST,
        ("Litsey reytingi", "Рейтинг лицея", "Lyceum rating"),
        "reyting reytingi рейтинг ученики топ лучшие rating top students ball очки",
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
        ("Sababli yoʻqlik", "Справки об отсутствии", "Absence excuses"),
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
        "staff-homework",
        "staff",
        "/homework/",
        _TE,
        ("Uy vazifalari", "Домашние задания", "Homework"),
        "uy vazifa vazifalar домашнее задание задания homework assignments emis "
        "topshirish сдача submissions",
    ),
    _d(
        "staff-homework-review",
        "staff",
        "/homework/?only=to_review",
        _TE,
        (
            "Uy vazifalarini tekshirish",
            "Проверка домашних заданий",
            "Homework review",
        ),
        "tekshirish baholash izoh qaytarish проверка оценить комментарий вернуть "
        "review grade comment return submissions homework",
    ),
    _d(
        "staff-students",
        "staff",
        "/students/",
        _TE,
        ("Oʻquvchilarni qidirish", "Поиск учеников", "Student search"),
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
        ("Maʼlumotnomalar", "Справки", "Certificates"),
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
        ("Sababli yoʻqlik", "Справки об отсутствии", "Absence excuses"),
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
        ("Oʻquvchilar", "Ученики", "Students"),
        "oquvchi oquvchilar ученик ученики student students",
    ),
    _d(
        "admin-teachers",
        "admin",
        "/teachers/",
        _AD,
        ("Oʻqituvchilar", "Учителя", "Teachers"),
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
        "admin-day-blocks",
        "admin",
        "/day-blocks/",
        _AD,
        ("Darsdan tashqari bloklar", "Неучебные блоки", "Non-lesson blocks"),
        "tushlik tanaffus yigʻilish обед перерыв линейка неучебные блоки "
        "lunch break assembly day blocks non-lesson",
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
        ("Maʼlumotnomalar", "Справки", "Certificates"),
        "malumotnoma spravka справка справки certificate certificates",
    ),
    _d(
        "admin-certificate-types",
        "admin",
        "/certificate-types/",
        _AD,
        ("Maʼlumotnoma turlari", "Типы справок", "Certificate types"),
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
        ("Eʼlonlar", "Рассылки", "Broadcasts"),
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
        "admin-bots",
        "admin",
        "/bots/",
        _AD,
        ("Botlar", "Боты", "Bots"),
        "bot botlar боты telegram token",
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
        "admin-migration",
        "admin",
        "/migration/",
        _AD,
        ("Serverni koʻchirish", "Перенос на другой сервер", "Server migration"),
        "migration migratsiya перенос миграция сервер server move koʻchirish",
    ),
    _d(
        "admin-excuses",
        "admin",
        "/excuses/",
        _AD,
        ("Sababli yoʻqlik", "Справки об отсутствии", "Absence excuses"),
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
        "admin-essay-keys",
        "admin",
        "/essay-keys/",
        _AD,
        ("Esse kalitlari", "Ключи эссе", "Essay keys"),
        "esse kalit kalitlar ключи эссе шифрование essay keys backup restore rotate "
        "zaxira nusxa",
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
        ("Hisobni oʻchirish", "Удаление аккаунта", "Delete account"),
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
        ("Koʻrinish", "Оформление", "Appearance"),
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
        ("Roʻyxatlar", "Списки", "Lists"),
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
        ("Toʻplamlar", "Подборки", "Collections"),
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
        "mening kurslarim мои курсы my courses progress progress прогресс "
        "ai review ИИ-проверка проверка работы ish tekshiruvi",
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
        ("Kursga qoʻshilish", "Вступить в курс", "Join a course"),
        "qoshilish вступить код join code kurs курс invite",
    ),
    _d(
        "lms-badges",
        "lms",
        "/profile/",
        _ALL,
        ("Mening nishonlarim", "Мои значки", "My badges"),
        "nishon nishonlar значок значки награды badge badges achievements "
        "yutuqlar достижения",
    ),
    _d(
        "lms-badge-designer",
        "lms",
        "/edit/badges/",
        _LMSA | _TE,
        ("Nishon konstruktori", "Конструктор значков", "Badge designer"),
        "nishon nishonlar значок значки badge badges konstruktor конструктор "
        "designer qoida правило rule",
    ),
    _d(
        "lms-review",
        "lms",
        "/review/",
        _ALL,
        ("Kunlik takrorlash", "Ежедневное повторение", "Daily review"),
        "takrorlash mashq повторение практика ошибки review practice mistakes "
        "kartochka карточки flashcards daily kunlik ежедневное",
    ),
    _d(
        "lms-progress",
        "lms",
        "/my/",
        _ALL,
        ("XP, seriya va topshiriqlar", "XP, серия и задания", "XP, streak and quests"),
        "xp streak seriya серия daraja уровень level topshiriq topshiriqlar квест "
        "квесты задания quest quests goal maqsad цель mastery oʻzlashtirish "
        "освоение карта map",
    ),
    _d(
        "lms-engagement-settings",
        "lms",
        "/edit/settings/",
        _LMSA | _TE,
        ("Faollik sozlamalari", "Настройки вовлечённости", "Engagement settings"),
        "faollik вовлечённость engagement threshold chegara порог mastery "
        "oʻzlashtirish освоение quest quests topshiriq квест задания sozlamalar "
        "настройки settings unlock ochish открытие",
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
    _d(
        "lms-certificates",
        "lms",
        "/edit/certificates/",
        _LMSA,
        (
            "Sertifikat konstruktori",
            "Конструктор сертификатов",
            "Certificate designer",
        ),
        "sertifikat sertifikatlar сертификат сертификаты certificate certificates "
        "konstruktor конструктор designer template shablon шаблон partner hamkor "
        "партнёр",
    ),
    _d(
        "lms-verify",
        "lms",
        "/verify/",
        _ALL,
        (
            "Sertifikatni tekshirish",
            "Проверка сертификата",
            "Verify a certificate",
        ),
        "tekshirish sertifikat проверка проверить сертификат verify certificate "
        "code kod код qr",
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
    _d(
        "bot-event",
        "bot",
        "/event",
        _ADM | {Role.STUDENT},
        ("Tadbir qo‘shish", "Добавить мероприятие", "Add an event"),
        "tadbir olimpiada imtihon мероприятие событие олимпиада экзамен event "
        "olympiad exam intake telegram bot",
    ),
    # - - - Admission (admission) - - -
    _d(
        "admission-home",
        "admission",
        "/",
        _ST,
        (
            "Universitetga kirish",
            "Поступление в университет",
            "University admission",
        ),
        "kirish universitet поступление университет admission university apply",
    ),
    _d(
        "admission-courses",
        "admission",
        "/courses/",
        _ST,
        ("Kurslarim", "Мои курсы", "My courses"),
        "kurslar kurs kitoblar kitob курсы курс книги книга courses course books "
        "library portfolio портфолио",
    ),
    _d(
        "admission-review",
        "admission",
        "/review/",
        _ST,
        ("Arizani AI tahlili", "AI-разбор заявки", "AI application review"),
        "tahlil ariza baho разбор заявки оценка проверка review application "
        "feedback strengths risks",
    ),
    _d(
        "admission-faq",
        "admission",
        "/faq/",
        _ST,
        ("Qabul boʼyicha FAQ", "FAQ о поступлении", "Admission FAQ"),
        "faq savollar maslahat вопросы ответы справка early decision test-optional "
        "transcript recommendation costs aid стоимость рекомендации транскрипт",
    ),
    _d(
        "admission-students",
        "admission",
        "/staff/",
        _ADM,
        ("Abituriyentlar", "Абитуриенты", "Applicants"),
        "abituriyent talaba абитуриенты ученики applicants students counselor "
        "mentor ментор консультант",
    ),
    _d(
        "admission-chooser",
        "admission",
        "/chooser/list/",
        _ST,
        ("Universitet tanlash", "Выбор университетов", "University chooser"),
        "universitet tanlash список университетов выбор вуз stipendiya стипендия "
        "university list chooser scholarships shortlist",
    ),
    _d(
        "admission-uni-chat",
        "admission",
        "/chooser/search/?view=discover",
        _ST,
        (
            "Universitet bo\u02bcyicha AI suhbat",
            "ИИ-чат по университету",
            "AI chat about a university",
        ),
        "universitet suhbat savol grant stipendiya чат вуз вопросы гранты "
        "стипендии требования university chat ask aid requirements research",
    ),
    _d(
        "admission-colleges-algorithm",
        "admission",
        "/chooser/search/?prefs=1",
        _ST,
        (
            "Kollej tanlash anketasi",
            "Анкета подбора колледжей",
            "College matching questionnaire",
        ),
        "anketa savollar moslik анкета вопросы подбор предпочтения "
        "questionnaire preferences matching algorithm",
    ),
    _d(
        "admission-countries",
        "admission",
        "/countries/",
        _ST,
        ("Mamlakatlar", "Страны", "Countries"),
        "mamlakat davlat viza maosh ish beruvchilar страны виза зарплата "
        "работодатели стоимость жизни countries visa salary employers cost living",
    ),
    _d(
        "admission-colleges-discover",
        "admission",
        "/chooser/search/?view=discover",
        _ST,
        (
            "Universitetlarni kashf etish",
            "Подбор университетов свайпом",
            "Discover universities",
        ),
        "kashf etish свайп подбор совпадение discover swipe matches "
        "universities interested",
    ),
    _d(
        "admission-journey",
        "admission",
        "/#journey",
        _ST,
        ("Qabul yo\u02bclim", "Путь поступления", "Admission journey"),
        "yo'l bosqich путь этапы поступление journey path steps roadmap",
    ),
    _d(
        "admission-documents",
        "admission",
        "/documents/",
        _ST,
        ("Hujjatlar", "Документы", "Documents"),
        "hujjat transkript документы транскрипт справка documents transcript "
        "admission",
    ),
    _d(
        "admission-deadlines",
        "admission",
        "/deadlines/",
        _ST,
        ("Muddatlar taqvimi", "Календарь сроков", "Deadline calendar"),
        "muddat taqvim kalendar сроки календарь дедлайны экспорт ics deadlines "
        "calendar export reminders",
    ),
    _d(
        "admission-consultations",
        "admission",
        "/help/",
        _ST,
        (
            "Maslahatlashuv",
            "Консультации с консультантом",
            "Consultations with a counselor",
        ),
        "maslahat maslahatchi mentor konsultatsiya консультация консультант "
        "ментор эссе проект запись consultation counselor mentor essay project "
        "book appointment documents process transcript",
    ),
    _d(
        "admission-staff-consultations",
        "admission",
        "/staff/consultations/",
        _ADM,
        ("Maslahatlar navbati", "Очередь консультаций", "Consultation queue"),
        "maslahat navbat qabul очередь консультаций принять предложить время "
        "consultation queue accept propose time counselor",
    ),
    _d(
        "admission-kb-editor",
        "admission",
        "/staff/kb/",
        _ADM,
        ("FAQ muharriri", "Редактор FAQ", "FAQ editor"),
        "faq savol javob bilimlar bazasi редактор вопросы ответы база знаний "
        "faq knowledge base editor",
    ),
    _d(
        "admission-items",
        "admission",
        "/activities/",
        _ST,
        ("Faoliyat va yutuqlar", "Активности и награды", "Activities and honors"),
        "faoliyat yutuq mukofot активности награды достижения activities honors "
        "extracurricular review",
    ),
    _d(
        "admission-essays",
        "admission",
        "/essays/",
        _ST,
        ("Insholar", "Эссе", "Essays"),
        "esse insho reja g'oya эссе сочинение черновик идеи essays personal "
        "statement draft ideas outline",
    ),
    _d(
        "admission-essay-review",
        "admission",
        "/essays/",
        _ST,
        (
            "Insho tahlili va ulashish",
            "Разбор и отправка эссе",
            "Essay review and sharing",
        ),
        "insho tahlil ulashish fikr эссе разбор обратная связь поделиться "
        "essay review share feedback",
    ),
    _d(
        "admission-essay-examples",
        "admission",
        "/essays/?tab=examples",
        _ST,
        (
            "Qabul qilingan insho namunalari",
            "Примеры принятых эссе",
            "Admitted essay examples",
        ),
        "insho namuna qabul qilingan эссе примеры принятые admitted essay "
        "examples excerpts samples",
    ),
    _d(
        "admission-budget",
        "admission",
        "/chooser/budget/",
        _ST,
        ("Topshirish byudjeti", "Бюджет подачи", "Application budget"),
        "byudjet narx badal to'lov бюджет стоимость подачи сбор waiver "
        "budget cost fee application fee aid css profile fafsa",
    ),
    _d(
        "admission-exemplars",
        "admission",
        "/staff/exemplars/",
        _ADM,
        ("Insho namunalari", "Образцы эссе", "Essay exemplars"),
        "insho namuna эссе образцы примеры exemplars admitted essays curate",
    ),
    _d(
        "admission-prompt-studio",
        "admission",
        "/staff/prompt-studio/",
        _ADM,
        ("Prompt studiyasi", "Студия промптов", "Prompt studio"),
        "prompt studiya промпт студия insho эссе essay prompts university "
        "prompt studio",
    ),
    _d(
        "admission-profile",
        "admission",
        "/settings/?tab=profile",
        _ST,
        ("Abituriyent profili", "Профиль абитуриента", "Applicant profile"),
        "profil sozlash профиль настройка абитуриент profile setup applicant",
    ),
    _d(
        "admission-outcomes",
        "admission",
        "/outcomes/",
        _ST,
        ("Qabul natijalari", "Результаты поступления", "Admission results"),
        "natija qabul qilindi rad результаты поступления приняли отказ "
        "outcomes results admitted rejected waitlisted where IHT students applied",
    ),
    _d(
        "admission-opportunities",
        "admission",
        "/opportunities/",
        _ST,
        ("Imkoniyatlar", "Возможности", "Opportunities"),
        "imkoniyat imtihon sertifikat olimpiada возможности экзамены сертификаты "
        "олимпиады курсы opportunities exams certifications courses events programs "
        "summer pre-college research stipendiya grant stipend scholarships "
        "fellowships grants free university courses стипендии гранты "
        "бесплатные курсы",
    ),
    _d(
        "admission-staff-opportunities",
        "admission",
        "/staff/opportunities/manage/",
        _ADM,
        (
            "Imkoniyatlarni boshqarish",
            "Управление возможностями",
            "Manage opportunities",
        ),
        "imkoniyat boshqarish tahrirlash arxiv возможности управление "
        "редактировать архив manage opportunities edit archive delete catalog",
    ),
    _d(
        "admission-staff-institutions",
        "admission",
        "/staff/universities/",
        _ADM,
        (
            "Universitetlar roʻyxati",
            "Список университетов",
            "Manage universities",
        ),
        "universitet roʻyxat tahrirlash университеты список редактировать "
        "manage universities institutions colleges catalog edit",
    ),
    _d(
        "admission-opportunities-plan",
        "admission",
        "/plan/",
        _ST,
        ("Imkoniyatlar rejasi", "План возможностей", "Opportunities plan"),
        "reja muddat 9-12 sinf план дедлайны 9-12 класс plan deadlines grades "
        "ai planner",
    ),
    _d(
        "admission-fellowships",
        "admission",
        "/opportunities/?kind=research",
        _ST,
        (
            "Stipendiyalar va tadqiqot",
            "Стипендии и исследования",
            "Fellowships and research",
        ),
        "tadqiqot stipendiya grant стипендии исследования гранты стажировка "
        "fellowships research grants internship",
    ),
    _d(
        "admission-opportunity-courses",
        "admission",
        "/opportunities/?kind=course",
        _ST,
        ("Kurslarni topish", "Поиск курсов", "Find courses"),
        "kurs onlayn kurslar курсы онлайн найти courses online find free mooc",
    ),
    _d(
        "admission-career",
        "admission",
        "/career/",
        _ST,
        ("Kasb va yo\u02bcnalish", "Профессия и направление", "Career and majors"),
        "kasb yo'nalish major minor spike профессия специальность направление "
        "career profession majors minors spike voice",
    ),
    _d(
        "admission-tasks",
        "admission",
        "/tasks/",
        _ST,
        ("Vazifalar", "Задачи", "Tasks"),
        "vazifa topshiriq muddat задачи дедлайн план tasks deadline todo board "
        "kanban timeline steps",
    ),
    _d(
        "admission-tests",
        "admission",
        "/tests/",
        _ST,
        ("Testlar va sertifikatlar", "Тесты и сертификаты", "Tests and certificates"),
        "sat act ielts toefl duolingo ap ib a-level cambridge olympiad score "
        "тест сертификат балл экзамен олимпиада test sertifikat natija imtihon",
    ),
    _d(
        "admission-essay-practice",
        "admission",
        "/essays/practice/",
        _ST,
        (
            "Insho mashqi",
            "Практика эссе",
            "Essay practice",
        ),
        "mashq kundalik yozish практика эссе ежедневное письмо practice daily "
        "writing streak warm-up",
    ),
    _d(
        "admission-essays-by-university",
        "admission",
        "/essays/?lens=uni",
        _ST,
        (
            "Universitet boʼyicha insholar",
            "Эссе по университетам",
            "Essays by university",
        ),
        "universitet insho guruh эссе университет группа промпт essays by "
        "university supplemental prompts common app",
    ),
    _d(
        "admission-essay-ideas",
        "admission",
        "/essays/?tab=ideas",
        _ST,
        (
            "Insho gʼoyalari",
            "Идеи для эссе",
            "Essay ideas",
        ),
        "gʼoya mavzu brainstorm идеи темы мозговой штурм essay ideas topics brainstorm",
    ),
    _d(
        "admission-essay-story",
        "admission",
        "/essays/?tab=story",
        _ST,
        (
            "Hayot hikoyam va 3 soʼz",
            "Моя история и три слова",
            "My story and three words",
        ),
        "hikoya uch soʼz hayot история три слова моя story three words life "
        "story voice",
    ),
    _d(
        "admission-essay-alignment",
        "admission",
        "/essays/?tab=alignment",
        _ST,
        (
            "Insholar va universitetlar mosligi",
            "Соответствие эссе университетам",
            "Essay alignment",
        ),
        "moslik insho universitet соответствие эссе вуз alignment essay "
        "coverage prompts",
    ),
    _d(
        "admission-professions",
        "admission",
        "/profile/professions/",
        _ST,
        (
            "Kasblar",
            "Профессии",
            "Professions",
        ),
        "kasb mutaxassislik профессии специальности professions careers majors",
    ),
    _d(
        "admission-weights",
        "admission",
        "/profile/",
        _ST,
        (
            "Men uchun muhim narsalar (radar)",
            "Что для меня важно (радар)",
            "What matters to me (radar)",
        ),
        "muhim radar ustuvorlik вес важно приоритеты радар weights priorities "
        "radar what matters",
    ),
    _d(
        "admission-profile-background",
        "admission",
        "/settings/?tab=profile&section=background",
        _ST,
        (
            "Profil: fon va qiziqishlar",
            "Профиль: фон и интересы",
            "Profile: background and interests",
        ),
        "fon qiziqish xizmat фон интересы услуги background interests services family",
    ),
    _d(
        "admission-profile-details",
        "admission",
        "/settings/?tab=profile&section=details",
        _ST,
        (
            "Profil: tafsilotlar",
            "Профиль: подробности",
            "Profile: details",
        ),
        "tafsilot uch soʼz подробности три слова details three words",
    ),
    _d(
        "admission-catalog",
        "admission",
        "/chooser/?step=match&view=list",
        _ST,
        (
            "Universitetlar katalogi",
            "Каталог университетов",
            "University catalog",
        ),
        "katalog universitetlar qidirish каталог университеты поиск catalog "
        "universities browse search",
    ),
    _d(
        "admission-list-graph",
        "admission",
        "/chooser/?step=list&view=graph",
        _ST,
        (
            "Roʼyxat grafigi",
            "График списка",
            "List graph",
        ),
        "grafik roʼyxat universitet график список вузы graph list chart reach "
        "target safety",
    ),
    _d(
        "admission-quiz",
        "admission",
        "/chooser/?step=quiz",
        _ST,
        (
            "Universitet tanlash testi",
            "Тест по подбору вузов",
            "University quiz",
        ),
        "test anketa savollar тест анкета вопросы quiz questionnaire preferences",
    ),
    _d(
        "admission-tasks-gantt",
        "admission",
        "/tasks/?view=gantt",
        _ST,
        (
            "Muddatlar va vazifalar (Gantt)",
            "Сроки и задачи (диаграмма)",
            "Deadlines and tasks (Gantt)",
        ),
        "gantt vazifa muddat диаграмма ганта задачи сроки gantt timeline "
        "deadlines tasks",
    ),
    _d(
        "admission-tasks-board",
        "admission",
        "/tasks/?view=board",
        _ST,
        (
            "Vazifalar taxtasi",
            "Доска задач",
            "Task board",
        ),
        "taxta vazifa kanban доска задачи канбан board kanban tasks",
    ),
    _d(
        "admission-plan-saved",
        "admission",
        "/plan/?view=saved",
        _ST,
        (
            "Saqlangan imkoniyatlar",
            "Сохранённые возможности",
            "Saved opportunities",
        ),
        "saqlangan imkoniyat сохранённые возможности избранное saved "
        "opportunities bookmarks favorites",
    ),
    _d(
        "admission-plan-personal",
        "admission",
        "/plan/",
        _ST,
        (
            "Oʻzim topgan imkoniyatlar",
            "Мои находки",
            "Your own finds",
        ),
        "oʻzim topgan shaxsiy imkoniyat свои находки личные возможности own "
        "finds personal opportunities external add",
    ),
    _d(
        "admission-calendar-export",
        "admission",
        "/deadlines/",
        _ST,
        (
            "Taqvimga qoʻshish (.ics)",
            "Добавить в календарь (.ics)",
            "Add to calendar (.ics)",
        ),
        "taqvim kalendar eksport ics календарь экспорт ics google apple outlook "
        "calendar export subscribe",
    ),
    _d(
        "admission-career-field",
        "admission",
        "/career/?tab=field",
        _ST,
        (
            "Yoʼnalishni tanlash",
            "Выбор направления",
            "Choose a field",
        ),
        "yoʼnalish soha направление область field major choose",
    ),
    _d(
        "admission-career-explore",
        "admission",
        "/career/?tab=explore",
        _ST,
        (
            "Kasblarni oʼrganish",
            "Изучение профессий",
            "Explore careers",
        ),
        "kasb oʼrganish профессии изучить explore careers professions",
    ),
    _d(
        "admission-honors",
        "admission",
        "/activities/?kind=honor",
        _ST,
        (
            "Mukofotlar va yutuqlar",
            "Награды и достижения",
            "Honors and awards",
        ),
        "mukofot yutuq награды достижения honors awards prizes olympiad",
    ),
    _d(
        "admission-opportunity-events",
        "admission",
        "/opportunities/?kind=event",
        _ST,
        (
            "Tadbirlar",
            "Мероприятия",
            "Events",
        ),
        "tadbir tanlov мероприятия события events competitions",
    ),
    _d(
        "admission-opportunity-programs",
        "admission",
        "/opportunities/?kind=program",
        _ST,
        (
            "Dasturlar",
            "Программы",
            "Programs",
        ),
        "dastur yozgi программы летние programs summer pre-college",
    ),
    _d(
        "admission-opportunity-certifications",
        "admission",
        "/opportunities/?kind=certification",
        _ST,
        (
            "Sertifikatlar",
            "Сертификаты",
            "Certifications",
        ),
        "sertifikat сертификаты certifications certificates exams",
    ),
    _d(
        "admission-notifications",
        "admission",
        "/notifications/",
        _ST,
        (
            "Bildirishnomalar",
            "Уведомления",
            "Notifications",
        ),
        "bildirishnoma xabar уведомления сообщения notifications alerts inbox",
    ),
    _d(
        "admission-assistant",
        "admission",
        "/assistant/",
        _ST,
        (
            "Qabul yordamchisi",
            "Помощник по поступлению",
            "Admission assistant",
        ),
        "yordamchi AI suhbat помощник ИИ чат assistant ai chat help mcp "
        "ulagich коннектор connector claude chatgpt",
    ),
    _d(
        "admission-trajectories",
        "admission",
        "/trajectories/",
        _ST,
        (
            "Taʼlim traektoriyalari",
            "Образовательные траектории",
            "Educational trajectories",
        ),
        "traektoriya yoʼl xarita траектория дорожная карта путь roadmap path",
    ),
    _d(
        "admission-staff-trajectories",
        "admission",
        "/staff/trajectories/",
        _ADM,
        (
            "Traektoriyalar muharriri",
            "Редактор траекторий",
            "Trajectory editor",
        ),
        "traektoriya muharrir траектории редактор trajectories editor roadmap",
    ),
    _d(
        "staff-ai-tools",
        "staff",
        "/ai-tools/",
        _TE,
        (
            "AI vositalari",
            "ИИ-инструменты",
            "AI tools",
        ),
        "ai vositalar ии инструменты ai tools generate yaratish генерация",
    ),
    _d(
        "staff-ai-tool",
        "staff",
        "/tool/",
        _TE,
        (
            "AI vositasi",
            "ИИ-инструмент",
            "AI tool",
        ),
        "ai vosita ии инструмент tool homework uy vazifasi проверка работы check work",
    ),
    _d(
        "staff-studio",
        "staff",
        "/studio/",
        _TE,
        (
            "Studiya (video va ovoz)",
            "Студия (видео и озвучка)",
            "Studio (video and voice-over)",
        ),
        "studiya video ovoz studio видео озвучка voice-over mp4 narration",
    ),
    _d(
        "staff-question-bank",
        "staff",
        "/bank/",
        _TE,
        (
            "Savollar banki",
            "Банк вопросов",
            "Question bank",
        ),
        "savollar banki банк вопросов question bank test mavzu тема topic fan "
        "предмет subject",
    ),
    _d(
        "lms-duo-path",
        "lms",
        "/duo/path/",
        _ALL,
        (
            "Duo yoʻli",
            "Путь Duo",
            "Duo path",
        ),
        "duo yoʻl путь path darslar уроки lessons trail",
    ),
    _d(
        "lms-duo-lesson",
        "lms",
        "/duo/lesson/",
        _ALL,
        (
            "Duo darsi",
            "Урок Duo",
            "Duo lesson",
        ),
        "duo dars урок lesson mashq практика practice",
    ),
    _d(
        "lms-duo-club",
        "lms",
        "/duo/club/",
        _ALL,
        (
            "Duo klubi",
            "Клуб Duo",
            "Duo club",
        ),
        "duo klub клуб club league liga лига",
    ),
    _d(
        "admin-activities",
        "admin",
        "/activities/",
        _AD,
        (
            "Faoliyatlar",
            "Активности",
            "Activities",
        ),
        "faoliyat imkoniyat faoliyatlar активности возможности opportunities "
        "activities",
    ),
    _d(
        "admin-activities-clubs",
        "admin",
        "/activities/clubs/",
        _AD,
        (
            "Klublar",
            "Клубы",
            "Clubs",
        ),
        "klub klublar клуб клубы clubs volunteers volontyorlar волонтёры",
    ),
    _d(
        "admin-activities-analytics",
        "admin",
        "/activities/analytics/",
        _AD,
        (
            "Faoliyat tahlili",
            "Аналитика активностей",
            "Activities analytics",
        ),
        "tahlil analitika аналитика активностей analytics statistics statistika",
    ),
    _d(
        "admin-activities-media",
        "admin",
        "/activities/media/",
        {Role.ADMIN, Role.ACTIVITIES_ADMIN},
        (
            "Klub media moderatsiyasi",
            "Модерация медиа клубов",
            "Club media moderation",
        ),
        "media moderatsiya shikoyat yashirish rasm video медиа модерация жалобы "
        "скрыть фото видео moderation reports hide photos videos albums",
    ),
    _d(
        "admin-activities-club-limits",
        "admin",
        "/activities/clubs/",
        {Role.ADMIN, Role.ACTIVITIES_ADMIN},
        (
            "Klub media limitlari",
            "Лимиты медиа клубов",
            "Club media limits",
        ),
        "limit kvota xotira hajm лимит квота хранилище размер limit quota "
        "storage size photo video",
    ),
    _d(
        "admin-lms-levels",
        "admin",
        "/lms-levels/",
        _AD,
        (
            "LMS darajalari",
            "Уровни LMS",
            "LMS levels",
        ),
        "daraja darajalar уровни level levels lms xp",
    ),
    _d(
        "admin-lms-badges",
        "admin",
        "/lms-badges/",
        _AD,
        (
            "LMS nishonlari",
            "Значки LMS",
            "LMS badges",
        ),
        "nishon nishonlar значки бейджи badge badges lms",
    ),
    _d(
        "sp-clubs",
        "sp",
        "/clubs",
        _ST,
        (
            "Klublar",
            "Клубы",
            "Clubs",
        ),
        "klub klublar клуб клубы clubs volunteers volontyorlar волонтёры",
    ),
    _d(
        "student-club-album",
        "sp",
        "/activities/album/",
        _ST,
        (
            "Klub albomi",
            "Альбом клуба",
            "Club album",
        ),
        "albom rasm video foto galereya альбом фото видео галерея album photos "
        "videos gallery",
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


# Pages of a switchable feature: hidden while its flag is off.
FEATURE_PAGES: Final[dict[str, str]] = {"admin-login-cues": "login_cues"}


def hidden_pages(features: FeaturesSettings) -> frozenset[str]:
    """Ids of the pages whose feature flag is off."""
    return frozenset(
        page for page, name in FEATURE_PAGES.items() if not getattr(features, name)
    )


def for_roles(
    urls: UrlsSettings,
    roles: frozenset[Role],
    hidden: frozenset[str] = frozenset(),
) -> list[Found]:
    """Every destination the roles may open, in map order, minus the hidden pages."""
    return [
        resolve(d, urls) for d in APP_MAP if visible_to(d, roles) and d.id not in hidden
    ]


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
    hidden: frozenset[str] = frozenset(),
) -> list[Found]:
    """Pages that fit the query, best first; only pages the roles may open."""
    normal = _normal(query).strip()
    tokens = _tokens(query)
    scored = [
        (_score(d, normal, tokens, locale), index, d)
        for index, d in enumerate(APP_MAP)
        if visible_to(d, roles) and d.id not in hidden
    ]
    ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))
    return [resolve(d, urls) for _, _, d in ranked[:limit]]
