"""A7: scope offers on the web, for people who have no Telegram button."""

from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.domain.user import User
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.identity.http.conftest import Api

OFFERS = "/v1/id/me/connectors/offers"


async def _offered(api: Api, login: str, name: str = "Claude") -> User:
    user = await api.world.add_user(roles={Role.STUDENT}, login=login)
    connector = McpConnector(
        id=new_id(),
        user_id=user.id,
        name=name,
        server="student",
        scopes=["schedule:read"],
        token_hash=f"hash-{new_id()}",
    )
    api.world.store.connectors[connector.id] = connector
    await api.world.auth.offer_mcp_scopes.execute()
    return user


async def test_list_then_accept(api: Api) -> None:
    """A7: the owner sees the offer, accepts it, and it leaves the list."""
    user = await _offered(api, "web.offer")
    api.login_as(user)

    listed = await api.client.get(OFFERS)
    assert listed.status_code == 200
    [offer] = listed.json()
    assert offer["server"] == "student"
    assert offer["connector_names"] == ["Claude"]
    assert "token" not in offer and "token_hash" not in offer

    answer = await api.client.post(
        f"{OFFERS}/{offer['id']}/decision", json={"grant": True}
    )
    assert answer.status_code == 200
    assert answer.json() == {"result": "granted", "connector_names": ["Claude"]}
    assert (await api.client.get(OFFERS)).json() == []


async def test_decline_and_foreign_offer(api: Api) -> None:
    """A7: another person's offer answers not_available and stays open (no IDOR)."""
    owner = await _offered(api, "web.owner")
    stranger = await api.world.add_user(login="web.stranger")
    api.login_as(owner)
    [offer] = (await api.client.get(OFFERS)).json()
    url = f"{OFFERS}/{offer['id']}/decision"

    api.login_as(stranger)
    foreign = await api.client.post(url, json={"grant": True})
    assert foreign.json()["result"] == "not_available"

    api.login_as(owner)
    assert (await api.client.get(OFFERS)).json() != []
    declined = await api.client.post(url, json={"grant": False})
    assert declined.json() == {"result": "declined", "connector_names": []}
