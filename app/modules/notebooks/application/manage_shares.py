"""Use case: the owner shares a notebook by link or with named people (NB-SHARE)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
    ShareLimitError,
    ShareRecipientNotFoundError,
    ShareUnsupportedError,
)
from app.modules.notebooks.domain.sharing import (
    MAX_SHARES,
    RECIPIENT_LIMIT,
    RECIPIENT_QUERY_MIN_CHARS,
    NotebookShare,
    ShareVia,
    hash_token,
    is_shareable,
    new_token,
    viewable,
)
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory, UserRef, UserStatus
from app.shared.rate_limit import RateLimiter

SEARCH_PER_MINUTE = 20
JOIN_PER_MINUTE = 10
WINDOW_SECONDS = 60
PEOPLE = (Role.STUDENT, Role.TEACHER)


@dataclass(frozen=True, slots=True)
class Recipient:
    """A person as the owner sees them: never a login or a contact."""

    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class ShareState:
    """Who has access, whether a link works and what stays private."""

    link_active: bool
    people: list[tuple[NotebookShare, str]]
    hidden_source_kinds: list[SourceKind]


def display_name(user: UserRef | None) -> str:
    """First and last name; empty for an account that is gone."""
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip()


async def _owned(
    uow: NotebooksUnitOfWork, actor: Actor, notebook_id: UUID, *, shareable: bool = True
) -> Notebook:
    """The caller's own notebook; a member of a course workspace gets a 404 too."""
    notebook = await load_notebook(uow, actor.user_id, notebook_id, write=True)
    if notebook.owner_id != actor.user_id:
        raise NotebookNotFoundError()
    if shareable and not is_shareable(notebook):
        raise ShareUnsupportedError()
    return notebook


class ManageShares:
    """Reads and changes who may open a notebook; every change works at once."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
        schedule: ScheduleQueries,
        rate_limiter: RateLimiter,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.schedule = schedule
        self.rate_limiter = rate_limiter

    async def state(self, actor: Actor, notebook_id: UUID) -> ShareState:
        """Return the link state, the people and the kinds that stay private."""
        async with self.uow_factory() as uow:
            await _owned(uow, actor, notebook_id, shareable=False)
            shares = await uow.shares.list_active(notebook_id)
            link = await uow.shares.link_exists(notebook_id)
            sources = await uow.sources.list_for_notebook(notebook_id)
        users = await self.identity.get_users([s.user_id for s in shares])
        shown = {source.id for source in viewable(sources)}
        hidden = sorted(
            {source.kind for source in sources if source.id not in shown},
            key=lambda kind: kind.value,
        )
        return ShareState(
            link, [(s, display_name(users.get(s.user_id))) for s in shares], hidden
        )

    async def create_link(self, actor: Actor, notebook_id: UUID) -> str:
        """Create the link or replace its token; people who joined keep access.

        Returns:
            The token, shown this once: only its hash is stored.
        """
        token = new_token()
        async with self.uow_factory() as uow:
            await _owned(uow, actor, notebook_id)
            await uow.shares.set_link(notebook_id, hash_token(token), self.clock.now())
            await uow.commit()
        return token

    async def delete_link(self, actor: Actor, notebook_id: UUID) -> None:
        """Turn the link off and remove the people who joined through it."""
        async with self.uow_factory() as uow:
            await _owned(uow, actor, notebook_id, shareable=False)
            await uow.shares.delete_link(notebook_id)
            for user_id in await uow.shares.delete_via(notebook_id, ShareVia.LINK):
                await uow.messages.delete_all(notebook_id, user_id)
            await uow.commit()

    async def add_person(self, actor: Actor, notebook_id: UUID, user_id: UUID) -> None:
        """Give a person access; this also lets a revoked person back in.

        Raises:
            InvalidOptionsError: The owner shares with themselves.
            ShareRecipientNotFoundError: No active account with this id.
            ShareLimitError: The notebook already has the maximum of people.
        """
        if user_id == actor.user_id:
            raise InvalidOptionsError(params={"reason": "share-self"})
        user = await self.identity.get_user(user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise ShareRecipientNotFoundError()
        async with self.uow_factory() as uow:
            await _owned(uow, actor, notebook_id)
            if await uow.shares.active(notebook_id, user_id) is None:
                if len(await uow.shares.list_active(notebook_id)) >= MAX_SHARES:
                    raise ShareLimitError(params={"limit": MAX_SHARES})
            await uow.shares.put(
                NotebookShare(notebook_id, user_id, ShareVia.DIRECT, self.clock.now())
            )
            await uow.commit()

    async def remove_person(
        self, actor: Actor, notebook_id: UUID, user_id: UUID
    ) -> None:
        """Revoke at once, delete the person's thread, keep them out of the link."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            await _owned(uow, actor, notebook_id, shareable=False)
            await uow.shares.put(
                NotebookShare(notebook_id, user_id, ShareVia.DIRECT, now, now)
            )
            await uow.messages.delete_all(notebook_id, user_id)
            await uow.commit()

    async def search_recipients(self, actor: Actor, query: str) -> list[Recipient]:
        """People by name, at most 10; 3 letters at least, so nobody lists the school.

        A student who has no other role finds only the active students of their own
        group; staff search every student and teacher.

        Raises:
            InvalidOptionsError: The request is shorter than 3 characters.
            RateLimitedError: More than 20 searches in a minute.
        """
        clean = " ".join(query.split())
        if len(clean) < RECIPIENT_QUERY_MIN_CHARS:
            raise InvalidOptionsError(params={"reason": "text-length", "max": 100})
        await self.rate_limiter.hit(
            f"share-search:{actor.user_id}",
            limit=SEARCH_PER_MINUTE,
            window_seconds=WINDOW_SECONDS,
        )
        if actor.roles == frozenset({Role.STUDENT}):
            found = await self._classmates(actor, clean)
        else:
            found = await self.identity.search_users(
                clean, roles=PEOPLE, limit=RECIPIENT_LIMIT + 1
            )
        people = [user for user in found if user.id != actor.user_id]
        return [Recipient(u.id, display_name(u)) for u in people[:RECIPIENT_LIMIT]]

    async def _classmates(self, actor: Actor, clean: str) -> list[UserRef]:
        """Active students of the actor's own group whose name contains the query."""
        me = await self.schedule.get_student(actor.user_id)
        if me is None:
            return []
        users = await self.identity.get_users(
            await self.schedule.group_user_ids([me.group_id])
        )
        wanted = clean.casefold()
        found = [
            user
            for user in users.values()
            if Role.STUDENT in user.roles and wanted in display_name(user).casefold()
        ]
        return sorted(found, key=display_name)

    async def join(self, actor: Actor, token: str) -> Notebook:
        """Turn a link into the caller's own grant.

        Raises:
            NotebookNotFoundError: Unknown token, a link that was turned off, a
                deleted notebook or a person the owner removed: all look the same.
            RateLimitedError: More than 10 tries in a minute.
        """
        await self.rate_limiter.hit(
            f"share-join:{actor.user_id}",
            limit=JOIN_PER_MINUTE,
            window_seconds=WINDOW_SECONDS,
        )
        async with self.uow_factory() as uow:
            notebook_id = await uow.shares.notebook_of_token(hash_token(token))
            if notebook_id is None:
                raise NotebookNotFoundError()
            notebook = await uow.notebooks.get(notebook_id)
            if notebook is None or not is_shareable(notebook):
                raise NotebookNotFoundError()
            if notebook.owner_id == actor.user_id:
                return notebook
            row = await uow.shares.find(notebook_id, actor.user_id)
            if row is not None and row.revoked_at is not None:
                raise NotebookNotFoundError()
            if row is None:
                await uow.shares.put(
                    NotebookShare(
                        notebook_id, actor.user_id, ShareVia.LINK, self.clock.now()
                    )
                )
                await uow.commit()
            notebook.can_write = False
            notebook.shared_view = True
            return notebook

    async def leave(self, actor: Actor, notebook_id: UUID) -> None:
        """The recipient drops the notebook and their thread; a new link can return."""
        async with self.uow_factory() as uow:
            if await uow.shares.active(notebook_id, actor.user_id) is None:
                raise NotebookNotFoundError()
            await uow.shares.delete(notebook_id, actor.user_id)
            await uow.messages.delete_all(notebook_id, actor.user_id)
            await uow.commit()

    async def list_shared(self, actor: Actor) -> list[tuple[Notebook, str]]:
        """Live notebooks shared with the caller and the name of their owner."""
        async with self.uow_factory() as uow:
            ids = await uow.shares.notebooks_of(actor.user_id)
            found = [await uow.notebooks.get(notebook_id) for notebook_id in ids]
        notebooks = [n for n in found if n is not None and is_shareable(n)]
        owners = await self.identity.get_users([n.owner_id for n in notebooks])
        for notebook in notebooks:
            notebook.can_write = False
            notebook.shared_view = True
            notebook.pinned = False
        return [(n, display_name(owners.get(n.owner_id))) for n in notebooks]
