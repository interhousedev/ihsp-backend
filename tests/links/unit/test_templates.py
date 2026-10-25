"""Public pages: every template renders in every language without raw keys."""

from datetime import date
from pathlib import Path

from app.modules.links.application.room_day import RoomDay
from app.modules.links.infrastructure.blocklist import DEFAULT_BLOCKLIST, load_blocklist
from app.modules.links.infrastructure.page_renderer import JinjaPageRenderer
from app.shared.i18n.core import I18nCore

import pytest

CONTEXTS: dict[str, dict[str, object]] = {
    "not_found": {},
    "gone": {},
    "disabled": {},
    "rate_limited": {"seconds": 42},
    "interstitial": {
        "destination": "https://example.org/?a=1&b=<2>",
        "report_url": "/s/x/report",
    },
    "report_form": {
        "action": "/s/x/report",
        "reasons": ["phishing", "malware", "personal_data", "offensive", "other"],
    },
    "report_done": {},
    "pin_form": {"room_name": "102", "day": "2026-10-05", "wrong": True},
}


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
@pytest.mark.parametrize("template", sorted(CONTEXTS))
def test_templates_render_without_missing_translations(
    i18n: I18nCore, template: str, locale: str
) -> None:
    """SL-4, ROOM-2: uz, ru and en pages have every string."""
    html = JinjaPageRenderer(i18n).render(template, locale, CONTEXTS[template])

    assert "links-" not in html
    assert "room-pin" not in html
    assert f'<html lang="{locale}">' in html
    assert 'name="robots" content="noindex"' in html


def test_values_are_escaped(i18n: I18nCore) -> None:
    """SL-4: a hostile URL cannot inject markup into the interstitial."""
    html = JinjaPageRenderer(i18n).render(
        "interstitial",
        "en",
        {
            "destination": 'https://x.test/"><script>alert(1)</script>',
            "report_url": "/r",
        },
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_room_page_escapes_titles(i18n: I18nCore) -> None:
    """ROOM-4: attachment titles come from the web and must be escaped."""
    from app.modules.links.application.room_day import (
        RoomAuthorLine,
        RoomItem,
        RoomLessonBlock,
    )

    item = RoomItem(
        "http://h/s/1", "h/s/1", "<img src=x onerror=alert(1)>", "http://h/s/1/report"
    )
    day = RoomDay(
        heading="h/r/1 · Tuesday 06.10",
        empty_text=None,
        lessons=(
            RoomLessonBlock(
                prefix="      ",
                period=1,
                time="08:30–09:15",
                summary="Physics",
                cancelled=False,
                materials=(item,),
                authors=(RoomAuthorLine("Ann", (item,)),),
            ),
        ),
        previous=(),
        today_href=None,
        day=date(2026, 10, 6),
    )

    html = JinjaPageRenderer(i18n).render("room", "en", {"day": day})

    assert "<img" not in html
    assert "&lt;img src=x" in html


def test_the_default_blocklist_loads_and_skips_comments(tmp_path: Path) -> None:
    """SL-8: one domain per line, comments and blanks ignored, lower-cased."""
    custom = tmp_path / "list.txt"
    custom.write_text("# comment\n\nEvil.Example\n  bad.test.  \n")

    assert load_blocklist(custom) == frozenset({"evil.example", "bad.test"})
    assert "blocked.example" in load_blocklist(DEFAULT_BLOCKLIST)
    assert not any(d.startswith("#") for d in load_blocklist())
