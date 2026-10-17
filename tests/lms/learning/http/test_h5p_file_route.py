"""The H5P file route: signed path is the only access, tight headers for the sandbox."""

from types import SimpleNamespace
from uuid import uuid4

from app.interfaces.http.v1.lms_learning import ROUTERS
from app.modules.lms.application.h5p_links import H5PLinks
from app.modules.lms.domain.h5p_token import package_prefix
from app.modules.lms.infrastructure.h5p_memory_store import MemoryH5PStore
from app.shared.clock import SystemClock
from tests.conftest import HttpClientFactory


async def test_package_files_need_no_cookie_and_carry_a_tight_policy(
    http_client: HttpClientFactory,
) -> None:
    store = MemoryH5PStore()
    course, package = uuid4(), uuid4()
    await store.put(package_prefix(course, package) + "h5p.json", b"{}", "x")
    links = H5PLinks(b"test-key", SystemClock(), store)
    learning = SimpleNamespace(h5p_links=links)
    client = await http_client(ROUTERS, None, lms=SimpleNamespace(learning=learning))
    base = links.launch(course, package).base_url

    response = await client.get(base + "h5p.json")  # no cookie, no Authorization

    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "sandbox allow-scripts" in csp
    assert "allow-same-origin" not in csp
    assert "connect-src 'self'" in csp and "frame-ancestors 'self'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["access-control-allow-origin"] == "*"
    assert "set-cookie" not in response.headers
    assert (
        await client.get(base.replace("/h5p/", "/h5p/x") + "h5p.json")
    ).status_code == 404
