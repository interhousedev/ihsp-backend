"""Share one guest bot answer with OpenUI blocks for seven days."""

import secrets
from datetime import timedelta

from app.modules.links.application.link_urls import LinkUrls
from app.modules.links.domain.errors import ShareNotAllowedError
from app.modules.links.ports.guest_answers import GuestAnswerStore, StoredGuestAnswer
from app.shared.clock import Clock
from app.shared.openui.visual import has_valid_blocks, keep_valid_blocks
from app.shared.rate_limit import RateLimiter

GUEST_PREFIX = "g-"
TOKEN_HEX_LENGTH = 32
GUEST_SHARE_TTL = timedelta(days=7)
SHARES_PER_DAY = 30
WINDOW_SECONDS = 86400


class ShareGuestAnswer:
    """Create `g-{token}` for an answer shown to a guest (parent, applicant)."""

    def __init__(
        self,
        *,
        store: GuestAnswerStore,
        rate_limiter: RateLimiter,
        clock: Clock,
        urls: LinkUrls,
    ) -> None:
        """Initialize the use case."""
        self.store = store
        self.rate_limiter = rate_limiter
        self.clock = clock
        self.urls = urls

    async def execute(self, *, telegram_user_id: int, text: str) -> str:
        """Store the valid blocks and return the public URL."""
        if not has_valid_blocks(text):
            raise ShareNotAllowedError(params={"target_id": "guest"})
        await self.rate_limiter.hit(
            f"guest-share:{telegram_user_id}",
            limit=SHARES_PER_DAY,
            window_seconds=WINDOW_SECONDS,
        )
        token = secrets.token_hex(TOKEN_HEX_LENGTH // 2)
        answer = StoredGuestAnswer(
            text=keep_valid_blocks(text), created_at=self.clock.now()
        )
        await self.store.put(token, answer, int(GUEST_SHARE_TTL.total_seconds()))
        return self.urls.share_url(f"{GUEST_PREFIX}{token}")
