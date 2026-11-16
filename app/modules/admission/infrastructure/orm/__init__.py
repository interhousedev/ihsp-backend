"""ORM of the admission schema; importing it registers every table."""

from app.modules.admission.infrastructure.orm.access import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.applications import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.catalog import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.help import *  # noqa: F401,F403
from app.modules.admission.infrastructure.orm.profile import *  # noqa: F401,F403
