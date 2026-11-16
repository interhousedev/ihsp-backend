"""The hub shows study/work sections by actual role."""

from app.interfaces.bot.keyboards import main_menu
from app.interfaces.bot.urls import BotUrls
from app.shared.actor import Role

import pytest

URLS = BotUrls(
    id_app="https://id.x/",
    sp="https://sp.x/",
    staff="https://staff.x/",
    admin="https://admin.x/",
    lms="https://lms.x/",
    library="https://lib.x/",
)


def i18n(key: str) -> str:
    return key


def _titles(roles: list[Role]) -> list[str]:
    return [r[0]["text"] for r in main_menu.get(i18n, roles, URLS) if len(r) == 1]


def test_student_study() -> None:
    assert "bot-menu-section-study" in _titles([Role.STUDENT])


def test_teacher_work() -> None:
    assert "bot-menu-section-work" in _titles([Role.TEACHER])


@pytest.mark.parametrize(
    "role", [Role.ADMIN, Role.COUNSELOR, Role.MENTOR, Role.TRANSCRIPT_OFFICER]
)
def test_other_roles_have_no_study_or_work(role: Role) -> None:
    titles = _titles([role])
    assert "bot-menu-section-study" not in titles
    assert "bot-menu-section-work" not in titles
    assert "bot-menu-section-account" in titles
