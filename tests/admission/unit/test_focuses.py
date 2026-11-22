"""Focuses: domain rules, quote check, what is served."""

import datetime as dt

from app.modules.admission.application.catalog_focuses_research import (
    FocusesOut,
    FocusItem,
    facts_from,
)
from app.modules.admission.domain.errors import CatalogFactInvalidError
from app.modules.admission.domain.focuses import (
    check_domains,
    on_domain,
    quote_in_page,
    served_focuses,
)

import pytest


def _item(url: str, verified: bool = True) -> dict[str, object]:
    return {"source_url": url, "verified": verified}


def test_on_domain() -> None:
    assert on_domain("https://mit.edu/a", "mit.edu")
    assert on_domain("https://admissions.mit.edu/a", "www.mit.edu")
    assert on_domain("https://mitadmissions.org/x", "mit.edu")
    assert not on_domain("https://evilmit.edu/x", "mit.edu")
    assert not on_domain("https://mitadmissions.org/x", "harvard.edu")
    assert not on_domain("http://mit.edu/a", "mit.edu")
    assert not on_domain("https://mit.edu/a", None)


def test_quote_in_page() -> None:
    page = "We value\n  \u201cintellectual   curiosity\u201d and  it\u2019s real."
    assert quote_in_page('We value "intellectual curiosity"', page)
    assert quote_in_page("it's real.", page)
    assert not quote_in_page("something else", page)
    assert not quote_in_page("  ", page)


def test_served_drops_unverified_and_off_domain() -> None:
    v = [
        _item("https://mit.edu/a"),
        _item("https://mit.edu/b", verified=False),
        _item("https://other.com/c"),
    ]
    assert served_focuses(v, "mit.edu") == [v[0]]
    assert served_focuses("x", "mit.edu") == []


def test_check_domains_raises() -> None:
    check_domains([_item("https://mit.edu/a")], "mit.edu")
    with pytest.raises(CatalogFactInvalidError):
        check_domains([_item("https://other.com/a")], "mit.edu")


def test_research_drops_unquoted_and_off_domain() -> None:
    def f(url: str, quote: str) -> FocusItem:
        return FocusItem(
            text_en="a", text_ru="б", text_uz="c", quote=quote, source_url=url
        )

    ok, bad_quote = "https://mit.edu/a", "https://mit.edu/b"
    pages = [
        {"url": ok, "text": "We seek builders."},
        {"url": bad_quote, "text": "Nothing."},
        {"url": "https://other.com/x", "text": "We seek builders."},
    ]
    out = FocusesOut(
        focuses=[
            f(ok, "We seek builders."),
            f(bad_quote, "We seek builders."),
            f("https://other.com/x", "We seek builders."),
            f("https://mit.edu/unseen", "We seek builders."),
        ]
    )
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    facts = facts_from(out, pages, "mit.edu", now)
    items = facts["focuses"]["value"]
    assert [x["source_url"] for x in items] == [ok]
    assert items[0]["verified"] is False
