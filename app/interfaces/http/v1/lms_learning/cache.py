"""Cache-Control value of the learning endpoints.

Every learner read depends on the caller (audience rules, enrolment, progress).
Browsers do not key their cache on Authorization, so a reused response could
show one account the page of another, or the rules before an edit.
"""

from typing import Final

PRIVATE_NO_STORE: Final = "private, no-store"
