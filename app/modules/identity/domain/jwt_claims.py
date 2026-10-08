"""Reading JWT payloads we received directly from Hydra."""

import base64
import json
from typing import Any


def unverified_claims(token: str) -> dict[str, Any]:
    """Return the payload of a JWT without checking the signature.

    Only for tokens that came straight from Hydra's token endpoint in the same
    request; never for tokens presented by a client.
    """
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
