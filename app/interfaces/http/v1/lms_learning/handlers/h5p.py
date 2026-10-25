"""H5P and interactive video routes of the learner player."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.interfaces.http.v1.lms_learning.schemas import (
    LearningH5PResultBody,
    LearningInteractionAnswerBody,
)
from app.modules.lms.application.h5p_links import H5PFileNotFound
from app.modules.lms.application.learning.views import (
    H5PLaunchView,
    LearningBlockResultView,
    LearningInteractionResultView,
)
from app.shared.actor import Actor

from fastapi import Depends, HTTPException, Response

# Package files never change (a new upload is a new package): cache them for the
# token's lifetime, but only in the browser.
H5P_FILE_CACHE = "private, max-age=3600"
# Package files are meant for a sandboxed frame (opaque origin) of the LMS page.
# Only the LMS origin (the same host: the API is proxied under it) may frame them;
# opened directly they get no same-origin rights and connect nowhere else.
PACKAGE_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "media-src 'self' data: blob: https:; font-src 'self' data:; "
    "connect-src 'self'; frame-src https://www.youtube-nocookie.com "
    "https://www.youtube.com https://player.vimeo.com; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'; "
    "sandbox allow-scripts allow-popups"
)
# An SVG opened directly must not run scripts on the LMS origin.
SVG_POLICY = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


async def get_h5p_launch(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> H5PLaunchView:
    """Return the signed base URL of the block's package (enrolled or staff)."""
    response.headers["Cache-Control"] = "no-store"
    view: H5PLaunchView = await container.lms.learning.get_h5p_launch.execute(
        actor, course_id, step_id, block_id
    )
    return view


async def record_h5p_result(
    step_id: UUID,
    block_id: str,
    body: LearningH5PResultBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningBlockResultView:
    """Store a `completed`/`answered` xAPI statement of the whole content."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    learning = container.lms.learning
    view: LearningBlockResultView = await learning.record_h5p_result.execute(
        actor, step_id, block_id, body.statement
    )
    return view


async def answer_interaction(
    step_id: UUID,
    block_id: str,
    interaction_id: str,
    body: LearningInteractionAnswerBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningInteractionResultView:
    """Grade an answer to a question of an interactive video."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    learning = container.lms.learning
    view: LearningInteractionResultView = await learning.answer_interaction.execute(
        actor, step_id, block_id, interaction_id, body.option_ids
    )
    return view


async def get_h5p_file(
    token: str,
    path: str,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Serve one file of a package; the signed token in the path is the access."""
    try:
        file = await container.lms.learning.h5p_links.read(token, path)
    except H5PFileNotFound as exc:
        raise HTTPException(status_code=404) from exc
    headers = {
        "Cache-Control": H5P_FILE_CACHE,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": PACKAGE_POLICY,
        # The frame has an opaque origin; the files carry no credentials (the token
        # in the path is the access), so any origin may read them.
        "Access-Control-Allow-Origin": "*",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }
    if file.content_type == "image/svg+xml":
        headers["Content-Security-Policy"] = SVG_POLICY
    return Response(file.data, media_type=file.content_type, headers=headers)
