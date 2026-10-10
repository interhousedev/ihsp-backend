"""LIB-1: `/robots.txt` lets crawlers into the library host only."""

from app.interfaces.http.public.robots import ROUTERS as ROBOTS_ROUTERS
from tests.conftest import HttpClientFactory


async def test_library_host_gets_its_own_robots_txt(
    http_client: HttpClientFactory,
) -> None:
    """LIB-1: public book pages and the sitemap are open on `lib.ihsu.uz`."""
    client = await http_client(ROBOTS_ROUTERS)

    library = await client.get("/robots.txt", headers={"host": "lib.ihsu.uz"})
    other = await client.get("/robots.txt", headers={"host": "s.ihsu.uz"})

    assert "Allow: /b/" in library.text and "Sitemap:" in library.text
    assert other.text == "User-agent: *\nDisallow: /\n"
