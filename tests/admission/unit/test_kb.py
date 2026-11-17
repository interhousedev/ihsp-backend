"""FAQ knowledge base: who reads, who edits, who sees drafts."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.kb import (
    ArticleChanges,
    ArticleDraft,
    KbService,
)
from app.modules.admission.domain.access import Entitlement
from app.modules.admission.domain.entitlement import AdmissionActor
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.kb import Article
from app.shared.actor import Actor, Role
from tests.fakes.clock import FixedClock


class FakeKb:
    """In-memory KbRepository; the query matches a substring of title or body."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[UUID, Article] = {}

    async def get(self, article_id: UUID) -> Article | None:
        return self.rows.get(article_id)

    async def search(
        self,
        *,
        query: str | None,
        locale: str | None,
        tag: str | None,
        status: str | None,
        limit: int,
    ) -> list[Article]:
        q = (query or "").lower()
        return [
            a
            for a in self.rows.values()
            if (status is None or a.status == status)
            and (locale is None or a.locale == locale)
            and (tag is None or tag in a.tags)
            and q in f"{a.title} {a.body}".lower()
        ][:limit]

    async def add(self, article: Article) -> None:
        self.rows[article.id] = article

    async def save(self, article: Article) -> None:
        self.rows[article.id] = article

    async def delete(self, article_id: UUID) -> bool:
        return self.rows.pop(article_id, None) is not None


def ctx(*roles: Role, applicant: bool = False) -> AdmissionContext:
    user = uuid4()
    entitlement = (
        Entitlement(user, "school_student", 2027, None, datetime.now(UTC))
        if applicant
        else None
    )
    staff = frozenset(r for r in roles if r in {Role.COUNSELOR, Role.MENTOR})
    return AdmissionContext(
        actor=Actor(user_id=user, roles=frozenset(roles)),
        admission=AdmissionActor(user, entitlement, staff),
        grade=11 if applicant else None,
        group_ids=frozenset(),
        assignments=(),
        mentor_opt_in=False,
    )


def draft(status: str = "published", **kw: object) -> ArticleDraft:
    fields: dict = {
        "title": "Early Decision",
        "body": "ED is **binding**.",
        "locale": "en",
        "status": status,
        "tags": [" Deadlines ", "deadlines", "ED"],
    }
    fields.update(kw)
    return ArticleDraft(**fields)


@pytest.fixture
def kb() -> KbService:
    return KbService(FakeKb(), FixedClock())


@pytest.mark.parametrize("role", [Role.ADMIN, Role.COUNSELOR, Role.MENTOR])
async def test_editors_create_update_delete(kb: KbService, role: Role) -> None:
    editor = ctx(role)
    article = await kb.create(editor, draft())
    assert article.tags == ["deadlines", "ed"]
    changed = await kb.update(editor, article.id, ArticleChanges(status="draft"))
    assert changed.status == "draft"
    await kb.delete(editor, article.id)
    with pytest.raises(AdmissionNotFoundError):
        await kb.get(editor, article.id)


@pytest.mark.parametrize(
    "caller",
    [
        ctx(Role.STUDENT, applicant=True),
        ctx(Role.TEACHER),
    ],
)
async def test_non_editors_are_refused(kb: KbService, caller: AdmissionContext) -> None:
    article = await kb.create(ctx(Role.COUNSELOR), draft())
    assert not kb.may_edit(caller)
    with pytest.raises(AdmissionForbiddenError):
        await kb.create(caller, draft())
    with pytest.raises(AdmissionForbiddenError):
        await kb.update(caller, article.id, ArticleChanges(title="x"))
    with pytest.raises(AdmissionForbiddenError):
        await kb.delete(caller, article.id)


async def test_drafts_hidden_from_readers(kb: KbService) -> None:
    counselor = ctx(Role.COUNSELOR)
    public = await kb.create(counselor, draft(title="Costs"))
    hidden = await kb.create(counselor, draft("draft", title="Secret"))
    for reader in (ctx(Role.STUDENT, applicant=True),):
        assert [a.id for a in await kb.search(reader)] == [public.id]
        with pytest.raises(AdmissionNotFoundError):
            await kb.get(reader, hidden.id)
    assert {a.id for a in await kb.search(counselor)} == {public.id, hidden.id}
    assert [a.id for a in await kb.published("secret", "en", 5)] == []


async def test_status_filter_applies_before_the_limit(
    kb: KbService, monkeypatch: pytest.MonkeyPatch
) -> None:
    counselor = ctx(Role.COUNSELOR)
    await kb.create(counselor, draft("draft", title="Old draft"))
    live = await kb.create(counselor, draft(title="Live"))
    monkeypatch.setattr("app.modules.admission.application.kb.SEARCH_LIMIT", 1)
    found = await kb.search(counselor, status="published")
    assert [a.id for a in found] == [live.id]
    reader = ctx(Role.STUDENT, applicant=True)
    assert await kb.search(reader, status="draft") == []


async def test_outsiders_cannot_read(kb: KbService) -> None:
    with pytest.raises(AdmissionForbiddenError):
        await kb.search(ctx(Role.STUDENT))


async def test_published_prefers_the_locale(kb: KbService) -> None:
    counselor = ctx(Role.COUNSELOR)
    await kb.create(counselor, draft(title="ED en"))
    ru = await kb.create(counselor, draft(title="ED ru", locale="ru"))
    found = await kb.published("ed", "ru", 2)
    assert found[0].id == ru.id
