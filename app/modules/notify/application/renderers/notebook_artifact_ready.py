"""Notice that a Studio output of a notebook is ready."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class NotebookArtifactReadyRenderer(DescribedRenderer):
    """Notice that a Studio output of a notebook is ready."""

    notification_type = NotificationType.NOTEBOOK_ARTIFACT_READY
    link_button_key = "notify-btn-open-notebook"
