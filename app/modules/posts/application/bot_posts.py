"""What the bot reads: posts visible to a viewer, and the /start mode choice."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.posts.application.admin_posts import ensure_root
from app.modules.posts.domain.bot_mode import BotMode
from app.modules.posts.domain.post import Post, Tree, Viewer
from app.modules.posts.ports.repositories import BotModeRepository, PostRepository


@dataclass(frozen=True, slots=True)
class PostScreen:
    """A post with its visible children; parent_id None for the root."""

    post: Post
    children: list[Post]
    parent_id: UUID | None


class BotPosts:
    """Reads the tree for the bot, filtered by audience."""

    def __init__(self, repo: PostRepository) -> None:
        """Store the repository."""
        self.repo = repo

    async def root(self, viewer: Viewer) -> PostScreen:
        """The main menu."""
        tree = await ensure_root(self.repo)
        assert tree.root is not None
        return self._screen(tree, tree.root, viewer)

    async def open(self, post_id: UUID, viewer: Viewer) -> PostScreen | None:
        """A post, or None when it is missing or hidden from the viewer."""
        tree = Tree(await self.repo.list_all())
        post = tree.by_id.get(post_id)
        if post is None or not tree.path_visible(post_id, viewer):
            return None
        return self._screen(tree, post, viewer)

    @staticmethod
    def _screen(tree: Tree, post: Post, viewer: Viewer) -> PostScreen:
        children = [c for c in tree.children(post.id) if c.visible_to(viewer)]
        return PostScreen(post, children, None if post.is_root else post.parent_id)


class BotModes:
    """The /start choice of a Telegram user."""

    def __init__(self, repo: BotModeRepository) -> None:
        """Store the repository."""
        self.repo = repo

    async def get(self, telegram_user_id: int) -> BotMode | None:
        """The stored choice."""
        return await self.repo.get(telegram_user_id)

    async def choose(self, telegram_user_id: int, mode: BotMode) -> None:
        """Store the choice."""
        await self.repo.set(telegram_user_id, mode)
