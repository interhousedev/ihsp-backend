"""`upload_file`: base64 and file-parameter uploads, and the SSRF rules."""

import base64
from collections.abc import Callable
from functools import partial

from app.interfaces.mcp import upload_file as tool_module
from app.interfaces.mcp.errors import (
    McpInvalidInputError,
    McpUploadDownloadFailedError,
    McpUploadTooLargeError,
    McpUploadUrlNotAllowedError,
)
from app.interfaces.mcp.upload_fetch import (
    SafeUploadFetcher,
    host_allowed,
    is_public,
    parse_hosts,
)
from app.shared.contracts.files import FileScope
from tests.mcp.conftest import World
from tests.mcp.helpers import call, data_of, text_of

import httpx
import pytest

ALLOWED = parse_hosts("files.oaiusercontent.com, *.example.org")
URL = "https://files.oaiusercontent.com/file-1?sig=x"


async def _public(host: str) -> list[str]:
    return ["93.184.216.34"]


def _resolver(*addresses: str) -> Callable[[str], object]:
    async def resolve(host: str) -> list[str]:
        return list(addresses)

    return resolve


class Counting(httpx.AsyncBaseTransport):
    """A transport that answers with `handler` and counts requests."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def _fetcher(
    transport: Counting, resolver: object = _public, max_bytes: int = 1000
) -> SafeUploadFetcher:
    return SafeUploadFetcher(
        allowed_hosts=ALLOWED,
        max_bytes=max_bytes,
        resolver=resolver,  # type: ignore[arg-type]
        transport=transport,
    )


def test_host_matching_is_exact_or_a_sub_domain() -> None:
    assert host_allowed("files.oaiusercontent.com", ALLOWED)
    assert host_allowed("a.example.org", ALLOWED)
    assert not host_allowed("example.org", ALLOWED)
    assert not host_allowed("evil-example.org", ALLOWED)
    assert not host_allowed("files.oaiusercontent.com.evil.test", ALLOWED)


def test_private_addresses_are_not_public() -> None:
    for address in (
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:10.0.0.1",
    ):
        assert not is_public(address), address
    assert is_public("93.184.216.34")


@pytest.mark.parametrize(
    "url",
    [
        "http://files.oaiusercontent.com/f",
        "https://user:pw@files.oaiusercontent.com/f",
        "https://files.oaiusercontent.com:8443/f",
        "https://evil.test/f",
        "https://127.0.0.1/f",
        "https://files.oaiusercontent.com.evil.test/f",
        "file:///etc/passwd",
    ],
)
async def test_unsafe_urls_are_refused_before_any_connection(url: str) -> None:
    transport = Counting(lambda r: httpx.Response(200, content=b"x"))

    with pytest.raises(McpUploadUrlNotAllowedError):
        await _fetcher(transport).fetch(url)

    assert transport.requests == []


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254"])
async def test_a_host_resolving_to_a_private_address_is_refused(address: str) -> None:
    transport = Counting(lambda r: httpx.Response(200, content=b"x"))

    with pytest.raises(McpUploadUrlNotAllowedError):
        await _fetcher(transport, _resolver(address)).fetch(URL)

    assert transport.requests == []


async def test_one_private_answer_among_public_ones_refuses() -> None:
    transport = Counting(lambda r: httpx.Response(200, content=b"x"))

    with pytest.raises(McpUploadUrlNotAllowedError):
        await _fetcher(transport, _resolver("93.184.216.34", "10.0.0.1")).fetch(URL)

    assert transport.requests == []


async def test_the_connection_goes_to_the_checked_address() -> None:
    transport = Counting(lambda r: httpx.Response(200, content=b"hello"))

    got = await _fetcher(transport).fetch(URL)

    assert got.data == b"hello" and got.name == "file-1"
    [request] = transport.requests
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "files.oaiusercontent.com"


async def test_a_redirect_to_another_host_is_checked_again() -> None:
    transport = Counting(
        lambda r: httpx.Response(302, headers={"location": "https://evil.test/x"})
    )

    with pytest.raises(McpUploadUrlNotAllowedError):
        await _fetcher(transport).fetch(URL)

    assert len(transport.requests) == 1


async def test_a_redirect_to_an_allowed_host_that_resolves_private_is_refused() -> None:
    answers = iter([["93.184.216.34"], ["10.0.0.1"]])

    async def resolve(host: str) -> list[str]:
        return next(answers)

    transport = Counting(
        lambda r: httpx.Response(302, headers={"location": "https://b.example.org/x"})
    )

    with pytest.raises(McpUploadUrlNotAllowedError):
        await _fetcher(transport, resolve).fetch(URL)

    assert len(transport.requests) == 1


async def test_redirect_loops_stop() -> None:
    transport = Counting(lambda r: httpx.Response(302, headers={"location": URL}))

    with pytest.raises(McpUploadUrlNotAllowedError):
        await _fetcher(transport).fetch(URL)

    assert len(transport.requests) == 4


async def test_the_declared_length_over_the_cap_refuses() -> None:
    transport = Counting(
        lambda r: httpx.Response(200, headers={"content-length": "5000"}, content=b"x")
    )

    with pytest.raises(McpUploadTooLargeError):
        await _fetcher(transport).fetch(URL)


async def test_a_stream_over_the_cap_is_cut() -> None:
    transport = Counting(lambda r: httpx.Response(200, content=b"x" * 1500))

    with pytest.raises(McpUploadTooLargeError):
        await _fetcher(transport).fetch(URL)


async def test_a_failing_status_is_a_download_error() -> None:
    transport = Counting(lambda r: httpx.Response(404))

    with pytest.raises(McpUploadDownloadFailedError):
        await _fetcher(transport).fetch(URL)


def test_base64_rules() -> None:
    assert tool_module.decode_base64("aGk=", " a.txt ") == ("a.txt", b"hi")
    with pytest.raises(McpInvalidInputError):
        tool_module.decode_base64("aGk=", None)
    with pytest.raises(McpInvalidInputError):
        tool_module.decode_base64("not base64!!", "a.txt")
    with pytest.raises(McpInvalidInputError):
        tool_module.decode_base64("", "a.txt")
    big = base64.b64encode(b"x" * (tool_module.MAX_BASE64_BYTES + 1)).decode()
    with pytest.raises(McpUploadTooLargeError):
        tool_module.decode_base64(big, "a.txt")


@pytest.mark.parametrize("server", ["student", "teacher"])
async def test_base64_upload_yields_a_ready_file_of_the_caller(
    world: World, server: str
) -> None:
    token, actor = world.connector_token(server, "files:write")

    async with world.serve() as running, running.session(server, token) as session:
        data = data_of(
            await call(session, "upload_file", name="a.txt", content_base64="aGVsbG8=")
        )

    assert data["name"] == "a.txt" and data["size"] == 5
    stored = world.files.files[next(iter(world.files.files))]
    assert str(stored.id) == data["file_id"]
    assert stored.owner_id == actor.user_id
    assert stored.status == "ready"
    expected = FileScope.STUDENT if server == "student" else FileScope.STAFF
    assert stored.scope == expected
    assert world.files.uploads[0][1] == b"hello"


async def test_a_file_parameter_is_downloaded_from_the_allowlist(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = Counting(lambda r: httpx.Response(200, content=b"from chatgpt"))
    monkeypatch.setattr(
        tool_module,
        "SafeUploadFetcher",
        partial(SafeUploadFetcher, resolver=_public, transport=transport),
    )
    token, _ = world.connector_token("student", "files:write")

    async with world.serve() as running, running.session("student", token) as session:
        data = data_of(
            await call(
                session,
                "upload_file",
                file={"download_url": URL, "file_id": "file-1"},
                name="work.txt",
            )
        )

    assert data["name"] == "work.txt"
    assert world.files.uploads[0][1] == b"from chatgpt"


async def test_a_file_parameter_with_a_foreign_url_is_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = Counting(lambda r: httpx.Response(200, content=b"x"))
    monkeypatch.setattr(
        tool_module,
        "SafeUploadFetcher",
        partial(SafeUploadFetcher, resolver=_public, transport=transport),
    )
    token, _ = world.connector_token("student", "files:write")

    async with world.serve() as running, running.session("student", token) as session:
        result = await call(
            session,
            "upload_file",
            file={"download_url": "http://169.254.169.254/x", "file_id": "f"},
        )

    assert result.isError
    assert transport.requests == []
    assert not world.files.files


async def test_both_or_neither_source_is_refused(world: World) -> None:
    token, _ = world.connector_token("student", "files:write")

    async with world.serve() as running, running.session("student", token) as session:
        neither = await call(session, "upload_file", name="a.txt")
        both = await call(
            session,
            "upload_file",
            name="a.txt",
            content_base64="aGk=",
            file={"download_url": URL, "file_id": "f"},
        )

    assert neither.isError and both.isError
    assert "exactly one" in text_of(neither)


async def test_the_tool_declares_its_file_parameter_and_needs_the_scope(
    world: World,
) -> None:
    token, _ = world.connector_token("student", "files:write")
    async with world.serve() as running, running.session("student", token) as session:
        listed = await session.list_tools()

    [tool] = [t for t in listed.tools if t.name == "upload_file"]
    assert tool.meta is not None and tool.meta["openai/fileParams"] == ["file"]

    other, _ = world.connector_token("student", "files:read")
    async with world.serve() as running, running.session("student", other) as session:
        result = await call(session, "upload_file", name="a.txt", content_base64="aGk=")
    assert result.isError and "insufficient_scope" in text_of(result)
