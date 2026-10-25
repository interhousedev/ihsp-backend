"""BOT-7, BOT-13, UF-BOT-06, UF-BOT-10: settings and Log out in the bot."""

from app.shared.contracts.academic import SubjectSummary
from app.shared.ids import new_id
from tests.bot.support.fakes import STUDENT_TG, TEACHER_TG
from tests.bot.support.harness import Harness

from aiogram.methods import SetChatMenuButton
from aiogram.types import MenuButtonDefault


def subject(name: str) -> SubjectSummary:
    """A subject of the student."""
    return SubjectSummary(
        subject_id=new_id(),
        name=name,
        teacher_names=(),
        semester_mark=None,
        emis_rating=None,
        absences=0,
        lessons_with_attendance=0,
    )


async def test_settings_menu_for_students(harness: Harness) -> None:
    """UF-BOT-06 step 1: language, notifications, lessons and Log out."""
    await harness.send("/settings")

    assert harness.last_text() == "bot-settings-main[language=Русский]"
    assert harness.last_labels() == [
        "bot-btn-language",
        "bot-btn-notifications",
        "bot-btn-lesson-settings",
        "bot-btn-logout",
        "bot-btn-back",
    ]


async def test_settings_menu_for_teachers_has_no_notifications(
    harness: Harness,
) -> None:
    """Teachers only have language, lesson settings and Log out."""
    await harness.press("m:settings", user_id=TEACHER_TG)

    assert harness.last_labels() == [
        "bot-btn-language",
        "bot-btn-lesson-settings",
        "bot-btn-logout",
        "bot-btn-back",
    ]


async def test_language_change_is_saved_and_the_screen_switches_language(
    harness: Harness,
) -> None:
    """UF-BOT-06 step 4: each change is saved immediately."""
    await harness.press("st:lang:uz")

    assert harness.world.identity_commands.patches == [{"locale": "uz"}]
    assert "uz" in harness.world.i18n.requested
    assert "✅ Oʻzbekcha" in harness.last_labels()


async def test_mark_type_toggle_is_saved_and_shown(harness: Harness) -> None:
    """BOT-13: mark types are toggles."""
    await harness.press("st:type:midterm")

    assert harness.world.identity_commands.patches == [
        {"marks_types": ["lesson", "final"]}
    ]
    assert "⬜ bot-mark-type-midterm" in harness.last_labels()
    assert "✅ bot-mark-type-lesson" in harness.last_labels()


async def test_mark_values_and_drop_alerts_are_toggles(harness: Harness) -> None:
    """BOT-13: values 2-5 and drop alerts."""
    await harness.press("st:value:2")
    await harness.press("st:drops:0")

    assert harness.world.identity_commands.patches == [
        {"marks_values": [3, 4, 5]},
        {"alerts_drops": False},
    ]
    assert "⬜ 2" in harness.last_labels()
    assert "⬜ bot-set-drops" in harness.last_labels()


async def test_thresholds_are_chosen_from_presets(harness: Harness) -> None:
    """BOT-12, BOT-13: off or one of the presets."""
    await harness.press("st:gpa_below:4.0")

    assert harness.world.identity_commands.patches == [{"alerts_gpa_below": 4.0}]
    assert "✅ 4.0" in harness.last_labels()
    assert "⬜ 3.5" in harness.last_labels()


async def test_an_invalid_value_changes_nothing(harness: Harness) -> None:
    """A tampered or stale button must not write anything."""
    await harness.press("st:gpa_below:9.9")

    assert harness.world.identity_commands.patches == []


async def test_subject_toggle_stores_the_other_subjects(harness: Harness) -> None:
    """BOT-13: subjects are loaded from the student's subjects."""
    world = harness.world
    world.marks.subjects = [subject("Physics"), subject("Art"), subject("Math")]
    await harness.press("st:open:subjects")
    assert harness.last_labels()[:3] == ["✅ Art", "✅ Math", "✅ Physics"]

    await harness.press("st:subject:1")  # Math

    stored = world.identity_commands.patches[-1]["marks_subject_ids"]
    by_name = {s.name: str(s.subject_id) for s in world.marks.subjects}
    assert stored == [by_name["Art"], by_name["Physics"]]
    assert "⬜ Math" in harness.last_labels()


async def test_lesson_settings_for_teachers_include_the_prompt_toggle(
    harness: Harness,
) -> None:
    """STF-10: lead time and the end-of-lesson prompt on or off."""
    await harness.press("st:open:lessons", user_id=TEACHER_TG)
    assert "✅ bot-set-prompt" in harness.last_labels()

    await harness.press("st:prompt:0", user_id=TEACHER_TG)
    await harness.press("st:lead:10", user_id=TEACHER_TG)

    assert harness.world.identity_commands.patches == [
        {"lessons_prompt_enabled": False},
        {"lessons_links_lead_min": 10},
    ]
    assert "⬜ bot-set-prompt" in harness.last_labels()


async def test_lesson_settings_for_students_have_no_prompt_toggle(
    harness: Harness,
) -> None:
    """The prompt toggle is for teachers only."""
    await harness.press("st:open:lessons")

    assert not any("bot-set-prompt" in label for label in harness.last_labels())


async def test_logout_asks_for_confirmation_first(harness: Harness) -> None:
    """UF-BOT-10 step 1: confirmation with a warning, nothing unlinked yet."""
    await harness.press("st:logout:ask")

    assert harness.last_text() == "bot-logout-confirm"
    assert harness.world.identity_commands.unlinked == []


async def test_logout_unlinks_clears_state_and_offers_login(harness: Harness) -> None:
    """BOT-7: confirmed Log out unlinks this Telegram account."""
    await harness.press("mc:new")  # leave an FSM state behind

    await harness.press("st:logout:yes")

    assert harness.world.identity_commands.unlinked == [STUDENT_TG]
    assert await harness.state_of(STUDENT_TG) is None
    assert harness.last_text() == "bot-login-welcome"
    reset = harness.session.calls(SetChatMenuButton)
    assert isinstance(reset[-1].menu_button, MenuButtonDefault)


async def test_after_logout_the_account_is_unlinked_for_the_bot(
    harness: Harness,
) -> None:
    """After Log out every message leads to Log in again."""
    await harness.press("st:logout:yes")

    await harness.send("/menu")

    assert harness.last_text() == "bot-login-welcome"
