"""The school week and the days a term may open beyond it.

ISO weekdays: 1 is Monday, 7 is Sunday. Monday to Friday are school days; EMIS knows
only those. Saturday and Sunday hold lessons only when the term has blocks on them.

Rows from before Saturday could be opened never come back: their entries have weekday
``RETIRED_WEEKDAY``, and Saturday lessons dated before ``WEEKEND_LESSONS_SINCE`` are
skipped by reads.
"""

import datetime as dt

SCHOOL_DAYS: tuple[int, ...] = (1, 2, 3, 4, 5)
WEEK_DAYS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
SATURDAY = 6
RETIRED_WEEKDAY = 0
WEEKEND_LESSONS_SINCE = dt.date(2026, 11, 5)
