"""Web description of every notification type: title, body and a link."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NamedTuple

from app.modules.notify.application.format import (
    fmt_date,
    fmt_datetime,
    fmt_number,
    join_names,
    strip_html,
)
from app.settings import UrlsSettings
from app.shared.i18n.core import I18nContext, I18nCore
from app.shared.notifications import NotificationType


class Description(NamedTuple):
    """What the notification center shows for one notification."""

    title: str
    body: str
    link: str | None


@dataclass(frozen=True, slots=True)
class _View:
    """Translation function and links for one reader."""

    t: I18nContext
    urls: UrlsSettings
    staff: bool

    def lesson_link(self, lesson_id: Any) -> str:
        """Link to the lesson page of the reader's app."""
        base = self.urls.staff if self.staff else self.urls.sp
        return f"{base}/lessons/view/?id={lesson_id}"


_Builder = Callable[[dict[str, Any], _View], Description]


def _mark_type(v: _View, mark_type: Any) -> str:
    key = f"notify-mark-type-{mark_type}"
    text = v.t(key)
    return str(mark_type) if text == key else text


def _marks(p: dict[str, Any], v: _View) -> Description:
    lines = [
        v.t(
            "notify-marks-line",
            subject=m.get("subject_name", ""),
            value=m.get("value", ""),
            type=_mark_type(v, m.get("type")),
            date=fmt_date(m.get("date")),
        )
        for m in p.get("marks", [])
    ]
    lines += [
        v.t(
            "notify-marks-change-line",
            subject=c.get("subject_name", ""),
            old=fmt_number(c.get("old")),
            new=fmt_number(c.get("new")),
        )
        for c in p.get("result_changes", [])
    ]
    return Description(
        v.t("notify-marks-title"), "\n".join(lines), f"{v.urls.sp}/grades/"
    )


def _result_drop(p: dict[str, Any], v: _View) -> Description:
    key = (
        "notify-result-drop-gpa"
        if p.get("scope") == "gpa"
        else "notify-result-drop-subject"
    )
    body = v.t(
        key,
        subject=p.get("subject_name", ""),
        old=fmt_number(p.get("old")),
        new=fmt_number(p.get("new")),
        semester=p.get("semester", ""),
    )
    return Description(v.t("notify-result-drop-title"), body, f"{v.urls.sp}/grades/")


def _result_below(p: dict[str, Any], v: _View) -> Description:
    key = {
        "gpa": "notify-result-below-gpa",
        "mark": "notify-result-below-mark",
    }.get(str(p.get("scope")), "notify-result-below-subject")
    body = v.t(
        key,
        subject=p.get("subject_name", ""),
        value=fmt_number(p.get("value")),
        threshold=fmt_number(p.get("threshold")),
    )
    return Description(v.t("notify-result-below-title"), body, f"{v.urls.sp}/grades/")


def lesson_head(p: dict[str, Any], t: I18nContext) -> str:
    """First line of a lesson message: groups, subject, period and room."""
    head = t(
        "notify-lesson-head",
        groups=join_names(p.get("group_names")),
        subject=p.get("subject_name", ""),
        period=p.get("period", ""),
    )
    if p.get("room_name"):
        head += t("notify-lesson-head-room", room=p["room_name"])
    return head


def _lesson_resources(p: dict[str, Any], v: _View) -> Description:
    return Description(
        v.t("notify-lesson-resources-title"),
        lesson_head(p, v.t),
        v.lesson_link(p.get("lesson_id", "")),
    )


def _lesson_prompt(p: dict[str, Any], v: _View) -> Description:
    return Description(
        v.t("notify-lesson-prompt-title"),
        v.t("notify-lesson-prompt-body", time=fmt_datetime(p.get("ends_at"))),
        f"{v.urls.staff}/lessons/view/?id={p.get('lesson_id', '')}",
    )


def _change_value(name: str, value: Any, v: _View) -> str:
    if value is None:
        return "—"
    if name == "status":  # "scheduled"/"cancelled" are shown in the reader's language
        key = f"notify-status-{value}"
        label = v.t(key)
        return str(value) if label == key else label
    return str(value)


def _lesson_changed(p: dict[str, Any], v: _View) -> Description:
    lines = [
        v.t(
            "notify-lesson-changed-head",
            subject=p.get("subject_name", ""),
            date=fmt_date(p.get("date")),
            period=p.get("period", ""),
        )
    ]
    for name, pair in (p.get("changes") or {}).items():
        old, new = (
            pair if isinstance(pair, list | tuple) and len(pair) == 2 else ("", pair)
        )
        key = f"notify-change-{name}"
        label = v.t(key)
        lines.append(
            v.t(
                "notify-change-line",
                field=name if label == key else label,
                old=_change_value(name, old, v),
                new=_change_value(name, new, v),
            )
        )
    return Description(
        v.t("notify-lesson-changed-title"),
        "\n".join(lines),
        v.lesson_link(p.get("lesson_id", "")),
    )


def _mail(p: dict[str, Any], v: _View) -> Description:
    return Description(v.t("notify-mail-title"), v.t("notify-mail-body"), None)


def _mail_bounced(p: dict[str, Any], v: _View) -> Description:
    return Description(
        v.t("notify-mail-bounced-title"),
        v.t("notify-mail-bounced-body", to=join_names(p.get("to"))),
        None,
    )


def _broadcast(p: dict[str, Any], v: _View) -> Description:
    title = str(p.get("title") or v.t("notify-broadcast-title"))
    return Description(title, strip_html(str(p.get("text", ""))), None)


def _emis_reauth(p: dict[str, Any], v: _View) -> Description:
    return Description(
        v.t("notify-emis-reauth-title"),
        v.t("notify-emis-reauth-body"),
        f"{v.urls.id}/security/emis/",
    )


def _files_expiring(p: dict[str, Any], v: _View) -> Description:
    body = v.t(
        "notify-files-expiring-body",
        count=p.get("files_count", ""),
        date=fmt_date(p.get("expires_on")),
    )
    return Description(v.t("notify-files-expiring-title"), body, f"{v.urls.sp}/files/")


def _telegram_linked(p: dict[str, Any], v: _View) -> Description:
    username = p.get("telegram_username")
    if username:
        body = v.t("notify-telegram-linked-body-username", username=username)
    else:
        body = v.t("notify-telegram-linked-body-id", id=p.get("telegram_user_id", ""))
    return Description(
        v.t("notify-telegram-linked-title"), body, f"{v.urls.id}/security/telegram/"
    )


def _otp_reset_requested(p: dict[str, Any], v: _View) -> Description:
    return Description(
        v.t("notify-otp-reset-title"),
        v.t("notify-otp-reset-body", time=fmt_datetime(p.get("effective_at"))),
        f"{v.urls.id}/security/",
    )


def _login_failures(p: dict[str, Any], v: _View) -> Description:
    key = (
        "notify-login-failures-body-ip" if p.get("ip") else "notify-login-failures-body"
    )
    body = v.t(key, count=p.get("count", ""), ip=p.get("ip", ""))
    return Description(
        v.t("notify-login-failures-title"), body, f"{v.urls.id}/security/"
    )


def _account_closing(p: dict[str, Any], v: _View) -> Description:
    return Description(
        v.t("notify-account-closing-title"),
        v.t("notify-account-closing-body", date=fmt_date(p.get("closes_on"))),
        None,
    )


def _mail_suspended(p: dict[str, Any], v: _View) -> Description:
    return Description(
        v.t("notify-mail-suspended-title"),
        v.t("notify-mail-suspended-body", reason=p.get("reason", "")),
        None,
    )


def _sync_alert(p: dict[str, Any], v: _View) -> Description:
    body = v.t(
        "notify-sync-alert-body", failed=p.get("failed", ""), total=p.get("total", "")
    )
    return Description(
        v.t("notify-sync-alert-title"), body, f"{v.urls.admin}/monitoring/"
    )


_BUILDERS: dict[NotificationType, _Builder] = {
    NotificationType.MARKS: _marks,
    NotificationType.RESULT_DROP: _result_drop,
    NotificationType.RESULT_BELOW: _result_below,
    NotificationType.LESSON_RESOURCES: _lesson_resources,
    NotificationType.LESSON_PROMPT: _lesson_prompt,
    NotificationType.LESSON_CHANGED: _lesson_changed,
    NotificationType.MAIL: _mail,
    NotificationType.MAIL_BOUNCED: _mail_bounced,
    NotificationType.BROADCAST: _broadcast,
    NotificationType.EMIS_REAUTH: _emis_reauth,
    NotificationType.FILES_EXPIRING: _files_expiring,
    NotificationType.TELEGRAM_LINKED: _telegram_linked,
    NotificationType.OTP_RESET_REQUESTED: _otp_reset_requested,
    NotificationType.LOGIN_FAILURES: _login_failures,
    NotificationType.ACCOUNT_CLOSING: _account_closing,
    NotificationType.MAIL_SUSPENDED: _mail_suspended,
    NotificationType.SYNC_ALERT: _sync_alert,
}


def describe(
    notification_type: NotificationType,
    payload: dict[str, Any],
    locale: str,
    *,
    i18n: I18nCore,
    urls: UrlsSettings,
    staff: bool = False,
) -> Description:
    """Return the title, body and link of a notification in the reader's language.

    `staff` picks the staff portal instead of the student app for lesson links.
    """
    view = _View(t=i18n.get_context(locale), urls=urls, staff=staff)
    return _BUILDERS[notification_type](payload, view)
