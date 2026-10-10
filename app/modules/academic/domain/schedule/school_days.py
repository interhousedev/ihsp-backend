"""The school week: lessons are held Monday to Friday, never on a Saturday.

ISO weekdays: 1 is Monday, 5 is Friday. Rows written before this rule may still
hold weekday 6 (Saturday), and lessons or moved days dated on a weekend; reads
skip them and nothing new is made for them.
"""

SCHOOL_DAYS: tuple[int, ...] = (1, 2, 3, 4, 5)
SATURDAY = 6
