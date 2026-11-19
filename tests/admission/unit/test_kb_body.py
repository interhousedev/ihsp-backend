"""ADM-U7: FAQ article bodies with OpenUI blocks and safe links."""

from app.modules.admission.application.kb import ArticleChanges, KbService
from app.modules.admission.domain.errors import KbBodyInvalidError
from app.modules.admission.domain.kb_body import check_body
from app.shared.actor import Role
from tests.admission.unit.test_kb import ctx, draft, kb  # noqa: F401

import pytest

_OK = 'root = LinkList([{title: "Site", url: "https://iht.uz"}])'


def _block(src: str = _OK) -> str:
    return f"```openui\n{src}\n```\n"


def test_valid_block_and_plain_markdown() -> None:
    """ADM-U7-1: a valid block and safe links pass."""
    check_body(
        "Intro\n\n" + _block() + "\n[a](https://iht.uz) [b](/faq) [c](mailto:a@b.uz)"
    )


def test_three_blocks_pass_four_fail() -> None:
    """ADM-U7-2: the limit is 3 blocks; the fourth is refused."""
    check_body(_block() * 3)
    with pytest.raises(KbBodyInvalidError):
        check_body(_block() * 4)


def test_block_size_boundary() -> None:
    """ADM-U7-3: 6000 characters pass the size check, 6001 are refused."""
    pad = "root = LinkList([])\n//"
    exact = pad + "x" * (6000 - len(pad))
    try:
        check_body(_block(exact))
    except KbBodyInvalidError as e:
        assert e.params["reason"] != "block_size"
    with pytest.raises(KbBodyInvalidError) as err:
        check_body(_block(exact + "x"))
    assert err.value.params["reason"] == "block_size"


def test_unclosed_fence_and_bad_program() -> None:
    """ADM-U7-4: an open fence and an invalid program are refused."""
    with pytest.raises(KbBodyInvalidError):
        check_body("```openui\n" + _OK)
    with pytest.raises(KbBodyInvalidError):
        check_body(_block("root = Nope(1)"))


@pytest.mark.parametrize(
    "link",
    [
        "[x](javascript:alert(1))",
        "[x](data:text/html,hi)",
        "[x](http://iht.uz)",
        "[x](//evil.example)",
        "![x](ftp://a/b.png)",
        "[x]: vbscript:run",
        "<file:///etc/passwd>",
        "<script>alert(1)</script>",
    ],
)
def test_unsafe_markdown_links_refused(link: str) -> None:
    """ADM-U7-5: only https, mailto and relative targets are allowed."""
    with pytest.raises(KbBodyInvalidError):
        check_body(f"Text {link}")


def test_openui_link_targets() -> None:
    """ADM-U7-6: relative and mailto pass in a block; others are refused."""
    for url in ("/faq/ed", "mailto:a@b.uz", "https://iht.uz"):
        check_body(_block(f'root = LinkList([{{title: "S", url: "{url}"}}])'))
    for url in ("javascript:x", "http://iht.uz", "//evil.example", "data:x"):
        with pytest.raises(KbBodyInvalidError):
            check_body(_block(f'root = LinkList([{{title: "S", url: "{url}"}}])'))


async def test_create_and_update_validate(kb: KbService) -> None:  # noqa: F811
    """ADM-U7-7: create and a body change are checked; a tag-only change is not."""
    editor = ctx(Role.ADMIN)
    with pytest.raises(KbBodyInvalidError):
        await kb.create(editor, draft(body="[x](javascript:1)"))
    article = await kb.create(editor, draft(body=_block()))
    with pytest.raises(KbBodyInvalidError):
        await kb.update(editor, article.id, ArticleChanges(body=_block() * 4))
    done = await kb.update(editor, article.id, ArticleChanges(tags=["new"]))
    assert done.tags == ["new"]
