"""Builds the library module: `container.library`.

The module is split in areas that share `LibraryCore`; each area has its own
`wiring_<area>.py` with a `<Area>Services` dataclass and a `build_<area>` function.
"""

from dataclasses import dataclass

from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.wiring_bridge import BridgeServices, build_bridge
from app.modules.library.wiring_catalogue import CatalogueServices, build_catalogue
from app.modules.library.wiring_core import CoreOverrides, LibraryCore, build_core
from app.modules.library.wiring_external import ExternalServices, build_external
from app.modules.library.wiring_materials import MaterialsServices, build_materials
from app.modules.library.wiring_reader import ReaderServices, build_reader
from app.modules.library.wiring_taxonomy import TaxonomyServices, build_taxonomy
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.wiring import ModuleDeps


@dataclass(frozen=True, slots=True)
class LibraryServices:
    """The library module as other layers see it."""

    core: LibraryCore
    catalogue: CatalogueServices
    taxonomy: TaxonomyServices
    materials: MaterialsServices
    reader: ReaderServices
    external: ExternalServices
    bridge: BridgeServices


def build(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    files: FilesApi,
    academic: AcademicDirectory,
    overrides: CoreOverrides | None = None,
) -> LibraryServices:
    """Wire the whole module over the given ports (real or fake)."""
    core = build_core(
        deps, identity=identity, files=files, academic=academic, overrides=overrides
    )
    return LibraryServices(
        core=core,
        catalogue=build_catalogue(core),
        taxonomy=build_taxonomy(core),
        materials=build_materials(core),
        reader=build_reader(core),
        external=build_external(core),
        bridge=build_bridge(core),
    )
