"""ID-4, ID-10, ID-26: templated emails with i18n."""

from email.message import EmailMessage

from app.modules.identity.domain.errors import EmailDeliveryError
from app.modules.identity.infrastructure.mailer.smtp import SmtpEmailSender, Transport
from app.settings import Settings
from app.shared.i18n.core import I18nCore

import aiosmtplib
import pytest


def sender(
    settings: Settings, i18n: I18nCore, transport: Transport | None = None
) -> SmtpEmailSender:
    """A sender with an in-memory transport."""
    return SmtpEmailSender(
        settings=settings.smtp_out, i18n=i18n, app_name="IHT", transport=transport
    )


def body_of(message: EmailMessage) -> str:
    """The HTML part."""
    html = message.get_body(("html",))
    assert html is not None
    return html.get_content()


def test_otp_email_contains_the_code_in_both_parts(
    settings: Settings, i18n: I18nCore
) -> None:
    """ID-4: the code is readable in text and HTML, in the user's language."""
    message = sender(settings, i18n).render(
        "ali@example.org", "otp", {"code": "123456"}, "en"
    )

    assert message["To"] == "ali@example.org"
    assert message["From"] == settings.smtp_out.system_from
    assert message["Subject"] == "Your IHT code"
    assert "123456" in body_of(message)
    text = message.get_body(("plain",))
    assert text is not None and "123456" in text.get_content()


def test_subject_follows_the_locale(settings: Settings, i18n: I18nCore) -> None:
    """GEN-3: Russian and Uzbek subjects exist."""
    ru = sender(settings, i18n).render("a@b.co", "otp", {"code": "1"}, "ru")
    uz = sender(settings, i18n).render("a@b.co", "otp", {"code": "1"}, "uz")

    assert ru["Subject"] == "Ваш код IHT"
    assert uz["Subject"] == "IHT kodingiz"


def test_activation_email_carries_the_link_and_login(
    settings: Settings, i18n: I18nCore
) -> None:
    """ID-10: the activation link and the expiry."""
    message = sender(settings, i18n).render(
        "t@example.org",
        "activation",
        {
            "name": "Kalandarova Gavxar",
            "login": "kalandarova.gavxar",
            "link": "https://id.example/activate/?token=abc",
            "hours": 72,
        },
        "en",
    )

    html = body_of(message)
    assert "https://id.example/activate/?token=abc" in html
    assert "kalandarova.gavxar" in html
    assert "72" in html


def test_user_supplied_text_is_html_escaped(settings: Settings, i18n: I18nCore) -> None:
    """Names go into HTML mail, so markup must not survive."""
    message = sender(settings, i18n).render(
        "t@example.org",
        "activation",
        {
            "name": "<script>x</script>",
            "login": "a.b",
            "link": "https://x",
            "hours": 72,
        },
        "en",
    )

    assert "<script>" not in body_of(message)


def test_notice_email_uses_the_given_text_key(
    settings: Settings, i18n: I18nCore
) -> None:
    """ID-21: notices render the text named by text_key."""
    message = sender(settings, i18n).render(
        "t@example.org",
        "notice",
        {
            "text_key": "id-mail-notice-email-changed",
            "text_params": {"new_email": "new@example.org"},
        },
        "en",
    )

    assert "new@example.org" in body_of(message)
    assert message["Subject"] == "IHT security notice"


def test_login_reminder_names_the_login(settings: Settings, i18n: I18nCore) -> None:
    """ID-26: the forgotten login is emailed."""
    message = sender(settings, i18n).render(
        "a@b.co", "login_reminder", {"login": "brastilov.aleksey"}, "en"
    )

    assert "brastilov.aleksey" in body_of(message)
    assert message["Subject"] == "Your IHT login"


async def test_send_hands_the_message_to_the_transport(
    settings: Settings, i18n: I18nCore
) -> None:
    """The relay receives the rendered message."""
    sent: list[EmailMessage] = []

    async def transport(message: EmailMessage) -> None:
        sent.append(message)

    await sender(settings, i18n, transport).send("a@b.co", "otp", {"code": "1"}, "en")

    assert [m["To"] for m in sent] == ["a@b.co"]


async def test_relay_errors_become_email_delivery_errors(
    settings: Settings, i18n: I18nCore
) -> None:
    """A broken relay is a typed 503."""

    async def broken(message: EmailMessage) -> None:
        raise aiosmtplib.SMTPConnectError("refused")

    with pytest.raises(EmailDeliveryError) as caught:
        await sender(settings, i18n, broken).send("a@b.co", "otp", {"code": "1"}, "en")

    assert caught.value.status == 503
