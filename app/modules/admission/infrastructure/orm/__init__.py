"""ORM of the admission schema; importing it registers every table."""

from app.modules.admission.infrastructure.orm.access import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.app_review import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.applications import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.calendar import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.career import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.catalog import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.consultations import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.kb import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.matching import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.memory_notes import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.opp_social import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.opportunities import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.outcomes import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.profile import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.student_chunks import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.supp_prompts import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.tasks import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.test_scores import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.uni_chat import *  # noqa: F401,F403
