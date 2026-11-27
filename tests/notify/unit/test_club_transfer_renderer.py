"""The club ownership offer: Accept and Decline buttons and the deep link."""

from app.modules.notify.application.renderers.clubs import ClubTransferOfferRenderer
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.contracts.callbacks import ClubTransferCb
from app.shared.contracts.notify import RenderContext
from app.shared.ids import new_id, uuid_to_b64
from tests.bot.support.fakes import KeyI18nCore, make_user


def _ctx() -> RenderContext:
    return RenderContext(user=make_user(Role.STUDENT), locale="en", telegram_user_id=1)


async def test_offer_has_buttons_and_deep_link() -> None:
    transfer = new_id()
    renderer = ClubTransferOfferRenderer(KeyI18nCore(), UrlsSettings())
    message = await renderer(
        {"club_id": "c1", "transfer_id": str(transfer), "club_name": {"en": "Chess"}},
        _ctx(),
    )
    assert message is not None and message.buttons is not None
    accept, decline = message.buttons[0]
    assert (
        accept["callback_data"] == ClubTransferCb(t=uuid_to_b64(transfer), d="a").pack()
    )
    assert decline["callback_data"].endswith(":d")
    link = message.buttons[1][0]["web_app_url"]
    assert link.endswith(f"/activities/club?id=c1&transfer={transfer}")


async def test_answer_has_only_the_link() -> None:
    renderer = ClubTransferOfferRenderer(KeyI18nCore(), UrlsSettings())
    message = await renderer(
        {"club_id": "c1", "transfer_id": str(new_id()), "result": "accepted"}, _ctx()
    )
    assert message is not None and message.buttons is not None
    assert len(message.buttons) == 1 and "callback_data" not in message.buttons[0][0]
