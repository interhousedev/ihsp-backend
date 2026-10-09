"""The JSON a push message carries to the service worker."""

import json
from dataclasses import dataclass, replace

MAX_PAYLOAD_BYTES = 3072
"""Push services accept about 4 KB after encryption; leave a margin."""

MAX_TITLE_CHARS = 120
MAX_BODY_CHARS = 1000
ELLIPSIS = "…"


@dataclass(frozen=True, slots=True)
class PushPayload:
    """What the service worker shows: title, body and where a click leads."""

    title: str
    body: str
    url: str
    tag: str
    notification_id: str
    type: str

    def to_json(self) -> str:
        """Compact JSON of at most `MAX_PAYLOAD_BYTES` bytes (the body is cut first)."""
        payload = replace(
            self,
            title=_cut(self.title, MAX_TITLE_CHARS),
            body=_cut(self.body, MAX_BODY_CHARS),
        )
        text = payload._dump()
        while _size(text) > MAX_PAYLOAD_BYTES and payload.body:
            payload = replace(
                payload, body=_cut(payload.body, len(payload.body) * 4 // 5)
            )
            text = payload._dump()
        if _size(text) > MAX_PAYLOAD_BYTES:
            payload = replace(payload, title=_cut(payload.title, 40))
            text = payload._dump()
        return text

    def _dump(self) -> str:
        return json.dumps(
            {
                "title": self.title,
                "body": self.body,
                "url": self.url,
                "tag": self.tag,
                "notification_id": self.notification_id,
                "type": self.type,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _cut(text: str, limit: int) -> str:
    """Shorten to `limit` characters, ending with an ellipsis when something is lost."""
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + ELLIPSIS
