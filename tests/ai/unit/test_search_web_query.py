"""The web search query leaves the school for the open web: it is cleaned and capped.

Links and e-mail addresses are removed and the length is capped at 300 characters.
The approval default stays on: a web search asks the student first.
"""

from app.modules.ai.application.tools.search_web import (
    QUERY_CHARS,
    SearchWebArgs,
    clean_query,
)
from app.settings import LimitsSettings

import pytest
from pydantic import ValidationError


def test_urls_are_removed_from_the_query() -> None:
    cleaned = clean_query("grades https://evil.example/x?s=123 and www.leak.io now")
    assert cleaned == "grades and now"


def test_e_mail_addresses_are_removed_from_the_query() -> None:
    assert clean_query("mail ali.sayfi+x@example.com about fees") == "mail about fees"


def test_the_query_is_capped_at_300_characters() -> None:
    cleaned = clean_query("word " * 200)
    assert len(cleaned) <= QUERY_CHARS == 300


def test_args_store_the_cleaned_query() -> None:
    args = SearchWebArgs(query="fees at https://a.example and x@y.org")
    assert args.query == "fees at and"


def test_args_with_only_a_link_are_refused() -> None:
    with pytest.raises(ValidationError):
        SearchWebArgs(query="https://only.a.link/path")


def test_a_long_query_is_capped_not_refused() -> None:
    args = SearchWebArgs(query="a" * 1000)
    assert len(args.query) == QUERY_CHARS


def test_ask_before_web_search_is_on_by_default() -> None:
    assert LimitsSettings().ai_ask_before_web_search == 1
