"""The one EMIS call whose endpoint IHSP does not know yet: a group's timetable.

Everything around it is built and tested against the ``EmisTimetableSource`` port
(``fetch_timetable`` is called by ``EmisClient.timetable``; the fake client answers
the same port). When the endpoint and its JSON are known, only the body of
``fetch_timetable`` below (plus a DTO and a mapper next to the other ones) changes.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.identity.application.register_models import EmisNotConfiguredError
from app.shared.contracts.emis import EmisTimetableItem

# ``get_json(path, token)`` is ``EmisClient.get_json``: it sends the token, raises
# ``EmisAuthError`` on HTTP 401 and ``EmisRequestError`` on other failures, and
# returns the whole parsed JSON body (``result`` or ``results`` is up to the mapper).
GetJson = Callable[[str, str], Awaitable[Any]]


async def fetch_timetable(get_json: GetJson, token: str) -> list[EmisTimetableItem]:
    """FILL IN: read the weekly timetable of the token's group from EMIS.

    Needed from the real endpoint:
      * the path and the HTTP method, and whether the group or the semester is a
        parameter (the student's token may already say which group);
      * for every row: weekday, pair (0-based or 1-based), subject id and names,
        teacher id and names, room, the half of the group (subgroup 1 or 2) and the
        week parity, if EMIS has them.

    Steps: ``body = await get_json("<path>", token)``; validate it with a
    ``...V1DTO`` in ``models/responses/timetable.py``; map each row to an
    ``EmisTimetableItem`` in ``mapping.py`` (``weekday`` 1-6, ``pair_number`` 0-based,
    names through ``title_case``, ``subgroup`` 1 or 2 or None, ``week_parity``
    ``every`` / ``odd`` / ``even``). Do not invent a URL: until it is known this
    raises ``EmisNotConfiguredError``, which the gateway reports as EMIS unavailable.
    """
    raise EmisNotConfiguredError("the EMIS timetable endpoint is not configured")
