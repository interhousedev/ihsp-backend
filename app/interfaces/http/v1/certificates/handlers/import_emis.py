"""POST /v1/certificates/me/import-emis."""

from app.interfaces.http.v1.certificates.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.certificates.schemas import ImportEmisResponse


async def import_emis(
    container: ContainerDep, actor: StudentActor
) -> ImportEmisResponse:
    """Import the caller's CEFR and national certificates from EMIS."""
    result = await container.certificates.import_emis.execute(actor.user_id)
    return ImportEmisResponse.from_result(result)
