"""Guest mode: the /start choice, the post tree, and the guest assistant."""

from uuid import UUID

from app.interfaces.bot.routers.guest.callbacks import PostCb
from app.modules.posts.application.admin_posts import PostDraft
from app.modules.posts.domain.post import Audience
from app.shared.actor import Actor, Role
from tests.bot.support.fakes import STUDENT_TG
from tests.bot.support.harness import Harness

GUEST = 8888
ADMIN = Actor(user_id=UUID(int=1), roles=frozenset({Role.ADMIN}))


async def test_choice_then_guest_menu_and_navigation(harness: Harness) -> None:
    posts = harness.world.container.posts
    about = await posts.admin.create(
        ADMIN, PostDraft(slug="about", title={"en": "About"}, body={"en": "**Hi**"})
    )
    await posts.admin.create(
        ADMIN,
        PostDraft(
            slug="students-only",
            title={"en": "Secret"},
            body={},
            audience=Audience.STUDENT,
        ),
    )
    await harness.send("/start", user_id=GUEST)
    assert harness.last_text() == "bot-guest-choice"

    await harness.press("sm:guest", user_id=GUEST)
    labels = harness.last_labels()
    assert "About" in labels and "Secret" not in labels

    await harness.press(PostCb.of(about.id).pack(), user_id=GUEST)
    assert "<b>Hi</b>" in (harness.edits[-1].text or "")
    assert "bot-guest-btn-back" in harness.last_labels()


async def test_guest_text_goes_to_guest_assistant(harness: Harness) -> None:
    await harness.send("/start", user_id=GUEST)
    await harness.press("sm:guest", user_id=GUEST)
    await harness.send("What are the fees?", user_id=GUEST)
    texts = [m.text for m in harness.sent] + [e.text for e in harness.edits]
    assert "ok" in texts
    assert not any((t or "").startswith("bot-login-welcome") for t in texts)


async def test_linked_student_start_keeps_main_menu(harness: Harness) -> None:
    await harness.send("/start", user_id=STUDENT_TG)
    assert harness.last_text() != "bot-guest-choice"
