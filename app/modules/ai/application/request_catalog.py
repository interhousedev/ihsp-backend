"""The AI requests every module declares, collected for the registry and publishing.

Each module's `wiring.py` exports `AI_REQUESTS`. This is the one list that names the
modules; a module with no declared request simply has an empty tuple.
"""

from app.modules.academic.wiring import AI_REQUESTS as ACADEMIC_REQUESTS
from app.modules.admission.wiring import AI_REQUESTS as ADMISSION_REQUESTS
from app.modules.ai.domain.requests import AiRequestSpec
from app.modules.ai.wiring import AI_REQUESTS as AI_MODULE_REQUESTS
from app.modules.lms.wiring import AI_REQUESTS as LMS_REQUESTS
from app.modules.notebooks.wiring import AI_REQUESTS as NOTEBOOKS_REQUESTS


def declared_requests() -> tuple[AiRequestSpec, ...]:
    """Every request the modules declare, in module order."""
    return (
        *AI_MODULE_REQUESTS,
        *NOTEBOOKS_REQUESTS,
        *ADMISSION_REQUESTS,
        *LMS_REQUESTS,
        *ACADEMIC_REQUESTS,
    )
