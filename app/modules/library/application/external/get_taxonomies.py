"""The filter lists of the UniLibrary search."""

from app.modules.library.application.external.gate import ExternalGate
from app.modules.library.application.external.views import AccessOption, TaxonomyView
from app.modules.library.application.locale import resolve_locale
from app.modules.library.ports.external_catalog import ExternalCatalog
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory
from app.shared.i18n.core import I18nCore

ACCESS_IDS = ("any", "open", "partial", "closed")


class GetTaxonomies:
    """LIB-5: types, fields and languages of UniLibrary, plus our access options."""

    def __init__(
        self,
        *,
        gate: ExternalGate,
        catalog: ExternalCatalog,
        identity: IdentityDirectory,
        i18n: I18nCore,
    ) -> None:
        """Take the gate, the catalogue and the translations of the access names."""
        self.gate = gate
        self.catalog = catalog
        self.identity = identity
        self.i18n = i18n

    async def execute(
        self, actor: Actor, accept_language: str | None = None
    ) -> TaxonomyView:
        """The lists in the user's language (cached by the catalogue).

        While UniLibrary is off the lists are empty (200), not a 404: the filters
        are a probe the pages make on load.
        """
        if not (await self.gate.flags()).enabled:
            return TaxonomyView(
                types=(), fields=(), languages=(), access=(), enabled=False
            )
        locale = await resolve_locale(self.identity, actor, accept_language)
        taxonomies = await self.catalog.taxonomies(locale)
        return TaxonomyView(
            types=taxonomies.types,
            fields=taxonomies.fields,
            languages=taxonomies.languages,
            access=tuple(
                AccessOption(
                    id=access,
                    name=self.i18n.t(locale, f"library-external-access-{access}"),
                )
                for access in ACCESS_IDS
            ),
            stale=taxonomies.stale,
        )
