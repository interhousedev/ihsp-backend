"""MAIL-2..4, UF-MAIL-02..04: browse, read, write, reply, forward, spam."""

from datetime import timedelta
from uuid import UUID

from app.shared.contracts.callbacks import MailCb, MailListCb
from app.shared.ids import uuid_to_b64
from tests.bot.support.fakes import NOW, STUDENT_TG, make_mail
from tests.bot.support.harness import Harness

LONG = "x" * 5000


def mail_cb(mail_id: UUID, action: str) -> str:
    """Callback data of an email button."""
    return MailCb(mail=uuid_to_b64(mail_id), action=action).pack()


async def test_mail_list_shows_the_last_10_emails_as_buttons(harness: Harness) -> None:
    """MAIL-3: the last 10 emails (sender, subject, date) as buttons, New email."""
    for index in range(12):
        harness.world.mail.add(
            make_mail(f"Subject {index}", occurred_at=NOW - timedelta(hours=index))
        )

    await harness.send("/mail")

    (call,) = harness.world.mail.recent_calls
    assert call["limit"] == 10
    labels = harness.last_labels()
    assert len([c for c in harness.last_callbacks() if c.startswith("ml:")]) == 10
    assert "bot-btn-new-mail" in labels
    assert "bot-btn-older" in labels
    assert labels[0].startswith("06.10 teacher: Subject 0")


async def test_older_page_continues_before_the_last_email(harness: Harness) -> None:
    """UF-MAIL-02: Older loads emails before the last one shown."""
    for index in range(12):
        harness.world.mail.add(
            make_mail(f"Subject {index}", occurred_at=NOW - timedelta(hours=index))
        )
    await harness.send("/mail")
    older = next(c for c in harness.last_callbacks() if c.startswith("mls:"))

    await harness.press(older)

    assert "bot-btn-newest" in harness.last_labels()
    assert harness.world.mail.recent_calls[-1]["before"] is not None
    assert len([c for c in harness.last_callbacks() if c.startswith("ml:")]) == 2


async def test_empty_mailbox_says_so(harness: Harness) -> None:
    """No emails gives a note and New email."""
    await harness.press(MailListCb(before=0).pack())

    assert "bot-mail-empty" in harness.last_text()
    assert "bot-btn-new-mail" in harness.last_labels()


async def test_opening_an_email_shows_it_with_its_buttons(harness: Harness) -> None:
    """UF-MAIL-02 step 2: tapping an email shows it again with Reply, Forward, Spam."""
    mail = harness.world.mail.add(make_mail("Exam"), html_telegram="<b>Room 5</b>")

    await harness.press(mail_cb(mail.id, "open"))

    text = harness.sent[-1].text
    assert text.startswith("<b>Exam</b>\nbot-mail-from[sender=teacher@example.com]")
    assert "<b>Room 5</b>" in text
    assert harness.last_callbacks() == [
        mail_cb(mail.id, "reply"),
        mail_cb(mail.id, "fwd"),
        mail_cb(mail.id, "spam"),
    ]


async def test_a_cut_body_has_show_full_and_sends_the_whole_text(
    harness: Harness,
) -> None:
    """MAIL-2: Show full appears when the body was cut and sends the full text."""
    mail = harness.world.mail.add(
        make_mail("Long"), html_telegram=LONG, text=LONG, truncated=True
    )
    await harness.press(mail_cb(mail.id, "open"))
    assert mail_cb(mail.id, "full") in harness.last_callbacks()

    await harness.press(mail_cb(mail.id, "full"))

    full_parts = [m.text for m in harness.sent[-2:]]
    assert sum(part.count("x") for part in full_parts) == 5000


async def test_a_purged_email_shows_only_the_snippet(harness: Harness) -> None:
    """UF-MAIL-02 alternative 2a: the full email was deleted after 30 days."""
    mail = harness.world.mail.add(
        make_mail("Old", purged=True, snippet="just a snippet")
    )

    await harness.press(mail_cb(mail.id, "open"))

    assert "bot-mail-purged" in harness.sent[-1].text
    assert "just a snippet" in harness.sent[-1].text
    assert mail_cb(mail.id, "full") not in harness.last_callbacks()


async def test_reply_flow_ends_with_mail_api_reply(harness: Harness) -> None:
    """UF-MAIL-04 step 1: Reply -> text -> preview -> Send calls MailApi.reply."""
    mail = harness.world.mail.add(make_mail("Exam"))
    await harness.press(mail_cb(mail.id, "reply"))
    assert harness.sent[-1].text.startswith("bot-mail-ask-reply")

    await harness.send("I will be there")
    assert harness.last_text().startswith("bot-mail-preview-reply")
    assert harness.last_callbacks() == ["mc:send", "mc:edit", "x"]
    await harness.press("mc:send")

    assert harness.world.mail.replies == [
        {"mail_id": mail.id, "html": "I will be there"}
    ]
    assert harness.last_text().startswith("bot-mail-sent")
    assert await harness.state_of(STUDENT_TG) is None


async def test_reply_keeps_telegram_formatting_as_html(harness: Harness) -> None:
    """MAIL-4: the message's formatting is converted with html_text."""
    mail = harness.world.mail.add(make_mail("Exam"))
    await harness.press(mail_cb(mail.id, "reply"))

    await harness.send("bold", entities=[{"type": "bold", "offset": 0, "length": 4}])
    await harness.press("mc:send")

    assert harness.world.mail.replies[0]["html"] == "<b>bold</b>"


async def test_new_email_flow_asks_to_subject_body_then_sends(harness: Harness) -> None:
    """UF-MAIL-03: recipient, subject, body, preview, Send."""
    await harness.press("mc:new")
    assert harness.sent[-1].text == "bot-mail-ask-to"

    await harness.send("friend@example.com, Boss@Example.com")
    assert harness.last_text() == "bot-mail-ask-subject"
    await harness.send("Hello   there")
    assert harness.last_text() == "bot-mail-ask-body"
    await harness.send("See you")
    assert harness.last_text().startswith("bot-mail-preview-new")
    await harness.press("mc:send")

    assert harness.world.mail.sent == [
        {
            "to": ["friend@example.com", "boss@example.com"],
            "subject": "Hello there",
            "html": "See you",
        }
    ]


async def test_every_input_step_has_cancel(harness: Harness) -> None:
    """BOT-4: each question comes with a Cancel button."""
    await harness.press("mc:new")
    assert harness.last_callbacks() == ["x"]
    await harness.send("friend@example.com")
    assert harness.last_callbacks() == ["x"]
    await harness.send("Subject")
    assert harness.last_callbacks() == ["x"]


async def test_invalid_address_is_asked_again(harness: Harness) -> None:
    """UF-MAIL-03 alternative 1a: an invalid address is asked again."""
    await harness.press("mc:new")

    await harness.send("not-an-address")

    assert harness.last_text() == "bot-mail-bad-address"
    assert await harness.state_of(STUDENT_TG) == "MailStates:new_to"


async def test_too_many_recipients_are_refused(harness: Harness) -> None:
    """MAIL-6: at most 5 recipients per email."""
    await harness.press("mc:new")

    await harness.send(" ".join(f"a{i}@example.com" for i in range(6)))

    assert harness.last_text() == "bot-mail-too-many[limit=5]"


async def test_a_file_where_text_is_expected_is_refused(harness: Harness) -> None:
    """The step stays open when the student sends something that is not text."""
    await harness.press("mc:new")

    await harness.send_voice(user_id=STUDENT_TG)

    assert harness.last_text() == "bot-mail-text-only"
    assert await harness.state_of(STUDENT_TG) == "MailStates:new_to"


async def test_forward_flow_with_a_note(harness: Harness) -> None:
    """UF-MAIL-04 step 2: recipient, optional note, preview, then forward."""
    mail = harness.world.mail.add(make_mail("Exam"))
    await harness.press(mail_cb(mail.id, "fwd"))

    await harness.send("friend@example.com")
    assert harness.last_labels() == ["bot-btn-skip", "bot-btn-cancel"]
    await harness.send("FYI")
    await harness.press("mc:send")

    assert harness.world.mail.forwards == [
        {"mail_id": mail.id, "to": ["friend@example.com"], "note": "FYI"}
    ]


async def test_forward_note_can_be_skipped(harness: Harness) -> None:
    """The note is optional."""
    mail = harness.world.mail.add(make_mail("Exam"))
    await harness.press(mail_cb(mail.id, "fwd"))
    await harness.send("friend@example.com")

    await harness.press("mc:skip")
    await harness.press("mc:send")

    assert harness.world.mail.forwards[0]["note"] is None


async def test_edit_on_the_preview_asks_for_the_text_again(harness: Harness) -> None:
    """UF-MAIL-03 step 2: Edit lets the student rewrite the body."""
    await harness.press("mc:new")
    await harness.send("friend@example.com")
    await harness.send("Subject")
    await harness.send("first draft")

    await harness.press("mc:edit")
    await harness.send("second draft")
    await harness.press("mc:send")

    assert harness.world.mail.sent[0]["html"] == "second draft"


async def test_spam_marks_the_email_and_undo_restores_it(harness: Harness) -> None:
    """UF-MAIL-04 step 3: "Marked as spam" with Undo."""
    mail = harness.world.mail.add(make_mail("Buy now"))

    await harness.press(mail_cb(mail.id, "spam"))
    assert harness.last_text() == "bot-mail-marked-spam"
    assert harness.last_callbacks() == [mail_cb(mail.id, "unspam")]
    await harness.press(mail_cb(mail.id, "unspam"))

    assert harness.world.mail.spam_calls == [(mail.id, True), (mail.id, False)]
    assert harness.last_text().startswith("<b>Buy now</b>")


async def test_edit_on_a_reply_preview_asks_for_the_reply_again(
    harness: Harness,
) -> None:
    """Edit goes back to the step that produced the preview."""
    mail = harness.world.mail.add(make_mail("Exam"))
    await harness.press(mail_cb(mail.id, "reply"))
    await harness.send("first")

    await harness.press("mc:edit")

    assert harness.last_text().startswith("bot-mail-ask-reply")
    assert await harness.state_of(STUDENT_TG) == "MailStates:reply_body"


async def test_edit_on_a_forward_preview_asks_for_the_note_again(
    harness: Harness,
) -> None:
    """The forward note can be rewritten."""
    mail = harness.world.mail.add(make_mail("Exam"))
    await harness.press(mail_cb(mail.id, "fwd"))
    await harness.send("friend@example.com")
    await harness.send("note")

    await harness.press("mc:edit")

    assert harness.last_text() == "bot-mail-ask-note"
    assert await harness.state_of(STUDENT_TG) == "MailStates:forward_note"


async def test_an_empty_subject_is_asked_again(harness: Harness) -> None:
    """The subject must have text."""
    await harness.press("mc:new")
    await harness.send("friend@example.com")

    await harness.send("   ")

    assert harness.last_text() == "bot-mail-bad-subject[limit=200]"
    assert await harness.state_of(STUDENT_TG) == "MailStates:new_subject"


async def test_send_after_the_draft_expired_is_answered_not_crashed(
    harness: Harness,
) -> None:
    """The FSM lives one hour; an old Send button is a stale button."""
    await harness.press("mc:send")

    assert harness.toasts[-1].text == "bot-stale-button"
    assert harness.world.mail.sent == []


async def test_teachers_have_no_mailbox(harness: Harness) -> None:
    """Mail belongs to students (MAIL-1)."""
    await harness.send("/mail", user_id=2002)

    assert harness.last_text().startswith("bot-hint-unexpected")
