"""The HTML widget file route: the signed path is the access, a sandbox CSP always."""

from types import SimpleNamespace
from uuid import uuid4

from app.interfaces.http.v1.lms_learning import ROUTERS
from app.modules.lms.application.html_widget_links import HtmlWidgetLinks
from app.modules.lms.domain.html_widget import widget_prefix
from app.modules.lms.infrastructure.h5p_memory_store import MemoryH5PStore
from app.shared.clock import SystemClock
from tests.conftest import HttpClientFactory

import httpx


def _assert_sandboxed(response: httpx.Response) -> None:
    csp = response.headers["content-security-policy"]
    assert csp.startswith("sandbox allow-scripts;")
    for forbidden in ("allow-same-origin", "allow-top-navigation", "allow-popups"):
        assert forbidden not in csp
    for part in (
        "connect-src 'none'",
        "form-action 'none'",
        "base-uri 'none'",
        "script-src 'self' 'unsafe-inline'",
        "frame-ancestors http",
    ):
        assert part in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "cross-origin"
    assert "set-cookie" not in response.headers


async def test_widget_files_are_sandboxed_on_success_and_on_errors(
    http_client: HttpClientFactory,
) -> None:
    store = MemoryH5PStore()
    course, package = uuid4(), uuid4()
    prefix = widget_prefix(course, package)
    await store.put(prefix + "index.html", b"<p>hi</p>", "text/html")
    await store.put(prefix + "pic.svg", b"<svg><script>1</script></svg>", "x")
    links = HtmlWidgetLinks(b"test-key", SystemClock(), store)
    learning = SimpleNamespace(html_widget_links=links)
    client = await http_client(ROUTERS, None, lms=SimpleNamespace(learning=learning))
    base = links.launch(course, package).base_url

    page = await client.get(base + "index.html")
    assert page.status_code == 200 and page.text == "<p>hi</p>"
    assert page.headers["content-type"].startswith("text/html")
    _assert_sandboxed(page)
    assert page.headers["cache-control"] == "private, max-age=600"
    assert links.launch(course, package).expires_in == 600

    svg = await client.get(base + "pic.svg")
    assert svg.headers["content-type"].startswith("image/svg+xml")
    _assert_sandboxed(svg)

    for url in (
        base + "missing.js",
        base.replace("/html-widgets/", "/html-widgets/x") + "index.html",
        base + "x.php",
    ):
        missing = await client.get(url)
        assert missing.status_code == 404
        _assert_sandboxed(missing)
