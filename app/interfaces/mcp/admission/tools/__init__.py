"""One module per family of admission tools; staff tools live in `staff`."""

from app.interfaces.mcp.admission.tools import (
    application,
    calendar,
    catalog,
    documents,
    link_activity,
    memory,
    personal_plan,
    plans,
)

TOOL_MODULES = (
    application,
    documents,
    memory,
    catalog,
    plans,
    personal_plan,
    calendar,
    link_activity,
)
