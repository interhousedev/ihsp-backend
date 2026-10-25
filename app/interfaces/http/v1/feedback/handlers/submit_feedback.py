"""POST /v1/feedback."""

from app.interfaces.http.v1.feedback.deps import ContainerDep, UserActor
from app.interfaces.http.v1.feedback.schemas import FeedbackIn, FeedbackOut


async def submit_feedback(
    body: FeedbackIn, container: ContainerDep, actor: UserActor
) -> FeedbackOut:
    """Send feedback; 10 per day, attachments must be the caller's ready files."""
    view = await container.feedback.submit.execute(
        actor,
        kind=body.kind,
        area=body.area,
        title=body.title,
        description=body.description,
        attachment_file_ids=body.attachment_file_ids,
        page_url=body.page_url,
    )
    return FeedbackOut.of(view)
