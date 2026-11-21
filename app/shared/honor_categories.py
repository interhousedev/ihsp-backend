"""The one category set of honors (admission) and certificate types (certificates).

Both platforms tag an achievement with the same category so a certificate type and the
honor made from it read alike. Labels live in the web apps (`honorCategory.*`).
"""

from typing import Final, Literal, get_args

HonorCategory = Literal[
    "olympiad",
    "award",
    "scholarship",
    "research",
    "leadership",
    "arts",
    "sports",
    "academic",
    "other",
]
HONOR_CATEGORIES: Final[tuple[str, ...]] = get_args(HonorCategory)
"""olympiad: olympiads and competitions; award: prizes and medals; scholarship: grants;
research: research and publications; leadership: leadership and service; arts; sports;
academic: grades, exams and certified skills; other."""
