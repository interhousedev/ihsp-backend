"""Offers of new MCP scopes on the connectors page, for people without Telegram."""

from uuid import UUID

from app.interfaces.http.v1.id.connectors.schemas import (
    ScopeOfferDecisionBody,
    ScopeOfferDecisionResponse,
    ScopeOfferResponse,
)
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep


async def get_scope_offers(actor: ActorDep, auth: AuthDep) -> list[ScopeOfferResponse]:
    """The caller's open offers."""
    offers = await auth.list_scope_offers.execute(actor.user_id)
    return [
        ScopeOfferResponse(
            id=offer.id,
            release_id=offer.release_id,
            server=offer.server,
            read_scopes=list(offer.read_scopes),
            write_scopes=list(offer.write_scopes),
            connector_names=list(offer.connector_names),
            expires_at=offer.expires_at,
        )
        for offer in offers
    ]


async def post_scope_offer_decision(
    offer_id: UUID, body: ScopeOfferDecisionBody, actor: ActorDep, auth: AuthDep
) -> ScopeOfferDecisionResponse:
    """Accept or decline; the same single-use rules as the Telegram buttons."""
    decision = await auth.decide_scope_offer.decide_by_id(
        offer_id, actor.user_id, grant=body.grant
    )
    return ScopeOfferDecisionResponse(
        result=decision.result.value,
        connector_names=list(decision.connector_names),
    )
