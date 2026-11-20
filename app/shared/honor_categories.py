"""The one category set of honors (admission) and certificate types (certificates).

Both platforms tag an achievement with the same category so a certificate type and the
honor made from it read alike. Labels live in the web apps (`honorCategory.*`).
"""

from typing import Final

HONOR_CATEGORIES: Final = (
    "olympiad",
    "award",
    "scholarship",
    "research",
    "leadership",
    "arts",
    "sports",
    "academic",
    "other",
)
"""olympiad: olympiads and competitions; award: prizes and medals; scholarship: grants;
research: research and publications; leadership: leadership and service; arts; sports;
academic: grades, exams and certified skills; other."""
