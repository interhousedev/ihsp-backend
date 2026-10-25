"""SL-9, UF-PUB-05: the no-JavaScript report form on short link pages."""

from app.modules.links.domain.link import LinkKind
from tests.fakes.links.world import LinksWorld

IP = "203.0.113.7"


async def _link_slug(world: LinksWorld) -> str:
    ann = world.person("Ann")
    view = await world.services.create_link.execute(
        ann, kind=LinkKind.URL, target_url="https://example.org/"
    )
    return view.link.slug


async def test_form_lists_the_reasons_and_posts_back(world: LinksWorld) -> None:
    """UF-PUB-05 step 1: phishing, malware, personal data, offensive, other."""
    slug = await _link_slug(world)

    page = await world.services.report_pages.show(slug, ip=IP, accept_language="en")

    assert page.status_code == 200
    assert page.html is not None
    for reason in ("phishing", "malware", "personal_data", "offensive", "other"):
        assert f'value="{reason}"' in page.html
    assert f'action="http://localhost:8000/s/{slug}/report"' in page.html
    assert 'method="post"' in page.html
    assert "links-report" not in page.html


async def test_submit_counts_the_report_and_thanks_the_visitor(
    world: LinksWorld,
) -> None:
    """UF-PUB-05 step 2: the counter goes up."""
    slug = await _link_slug(world)

    result = await world.services.report_pages.submit(
        slug, reason="malware", comment="bad", ip=IP, accept_language="en"
    )

    assert result.status_code == 202
    assert result.html is not None and "Thank you" in result.html
    link = next(iter(world.uow.store.links.values()))
    assert link.reports == 1


async def test_unknown_reason_is_treated_as_other(world: LinksWorld) -> None:
    """Hand-made form posts cannot break the report."""
    slug = await _link_slug(world)

    await world.services.report_pages.submit(
        slug, reason="<script>", comment=None, ip=IP, accept_language=None
    )

    metadata = world.uow.store.audits[-1].metadata
    assert metadata is not None
    assert metadata["reason"] == "other"


async def test_unknown_slug_shows_the_404_page(world: LinksWorld) -> None:
    """UF-PUB-03 1a: nothing to report."""
    shown = await world.services.report_pages.show("zzz", ip=IP, accept_language="en")
    sent = await world.services.report_pages.submit(
        "zzz", reason="other", comment=None, ip=IP, accept_language="en"
    )

    assert shown.status_code == 404
    assert sent.status_code == 404


async def test_too_many_reports_show_the_rate_limit_page(world: LinksWorld) -> None:
    """UF-PUB-05 1a: many reports from one IP."""
    slug = await _link_slug(world)
    for _ in range(10):
        await world.services.report_pages.submit(
            slug, reason="other", comment=None, ip=IP, accept_language=None
        )

    result = await world.services.report_pages.submit(
        slug, reason="other", comment=None, ip=IP, accept_language="en"
    )

    assert result.status_code == 429
    assert result.retry_after is not None
