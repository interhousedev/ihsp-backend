"""Bot routers, grouped by area (common, auth, student, teacher).

Routers are built by functions, never at module level: a Router can have one
parent only, so every dispatcher (production or one per test) builds its own.
"""

from aiogram import Router


def build_routers() -> list[Router]:
    """Build every router in the order they must be tried."""
    # Imported here so that importing the package stays cheap and cycle free.
    from app.interfaces.bot.routers.auth.login.router import build_router as login
    from app.interfaces.bot.routers.auth.security.router import build_router as security
    from app.interfaces.bot.routers.common.cancel.router import build_router as cancel
    from app.interfaces.bot.routers.common.chat_member.router import (
        build_router as chat_member,
    )
    from app.interfaces.bot.routers.common.menu.router import build_router as menu
    from app.interfaces.bot.routers.common.settings.router import (
        build_router as settings,
    )
    from app.interfaces.bot.routers.common.today.router import build_router as today
    from app.interfaces.bot.routers.common.unexpected.router import (
        build_router as unexpected,
    )
    from app.interfaces.bot.routers.student.homework.router import (
        build_router as homework,
    )
    from app.interfaces.bot.routers.student.mail.router import build_router as mail
    from app.interfaces.bot.routers.student.marks.router import build_router as marks
    from app.interfaces.bot.routers.teacher.current_lesson.router import (
        build_router as current_lesson,
    )
    from app.interfaces.bot.routers.teacher.homework_prompt.router import (
        build_router as homework_prompt,
    )
    from app.interfaces.bot.routers.teacher.lesson_prompt.router import (
        build_router as lesson_prompt,
    )
    from app.interfaces.bot.routers.teacher.resources.router import (
        build_router as resources,
    )

    builders = [
        cancel,
        chat_member,
        security,
        login,
        menu,
        today,
        marks,
        homework,
        mail,
        settings,
        current_lesson,
        lesson_prompt,
        homework_prompt,
        resources,
        unexpected,
    ]
    return [build() for build in builders]
