"""Checking the target of a new link: a safe URL or the caller's ready file."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.links.domain.errors import FileNotReadyError, InvalidLinkTargetError
from app.modules.links.domain.link import LinkKind
from app.modules.links.domain.url_policy import UrlPolicy
from app.modules.links.ports.title_fetcher import TitleFetcher
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose, FileRef, FilesApi, FileScope

READY = "ready"


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """A checked link target."""

    kind: LinkKind
    target_url: str | None
    file_id: UUID | None
    title: str | None
    file: FileRef | None


class TargetResolver:
    """Validates URLs (blocklist, title) and files (owner, status)."""

    def __init__(
        self, files: FilesApi, policy: UrlPolicy, titles: TitleFetcher
    ) -> None:
        """Store the files contract, the URL policy and the title fetcher."""
        self.files = files
        self.policy = policy
        self.titles = titles

    async def resolve(
        self,
        actor: Actor,
        *,
        kind: LinkKind,
        target_url: str | None,
        file_id: UUID | None,
    ) -> ResolvedTarget:
        """Return the checked target or raise a 422 error."""
        if kind is LinkKind.URL and target_url and file_id is None:
            checked = self.policy.check(target_url)
            title = await self.titles.fetch_title(checked.url)
            return ResolvedTarget(LinkKind.URL, checked.url, None, title, None)
        if kind is LinkKind.FILE and file_id is not None and not target_url:
            file = await self.files.get(file_id)
            if not _usable(file, actor):
                raise FileNotReadyError(params={"file_id": str(file_id)})
            return ResolvedTarget(LinkKind.FILE, None, file_id, None, file)
        raise InvalidLinkTargetError(params={"kind": kind.value})


def _usable(file: FileRef | None, actor: Actor) -> bool:
    return (
        file is not None
        and file.owner_id == actor.user_id
        and file.status == READY
        and file.purpose != FilePurpose.MAIL
        and file.scope != FileScope.LIBRARY  # the library serves its own files
    )
