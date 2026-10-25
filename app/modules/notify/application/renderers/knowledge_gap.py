"""An AI chat found nothing in the knowledge base, alert for Administration."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class KnowledgeGapRenderer(DescribedRenderer):
    """An AI chat found nothing in the knowledge base, alert for Administration."""

    notification_type = NotificationType.KNOWLEDGE_GAP
    link_button_key = "notify-btn-open-knowledge"
