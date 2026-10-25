"""Limits and choices of the feedback flow (the kinds and areas the module takes)."""

# Label keys are spelled out so that the catalogue check finds every one of them.
KIND_LABELS = {
    "idea": "bot-feedback-kind-idea",
    "bug": "bot-feedback-kind-bug",
    "other": "bot-feedback-kind-other",
}
AREA_LABELS = {
    "id": "bot-feedback-area-id",
    "my": "bot-feedback-area-my",
    "staff": "bot-feedback-area-staff",
    "admin": "bot-feedback-area-admin",
    "lms": "bot-feedback-area-lms",
    "library": "bot-feedback-area-library",
    "share": "bot-feedback-area-share",
    "bot": "bot-feedback-area-bot",
    "ai": "bot-feedback-area-ai",
    "notebooks": "bot-feedback-area-notebooks",
    "mail": "bot-feedback-area-mail",
    "other": "bot-feedback-area-other",
}
TITLE_MAX_CHARS = 120
DESCRIPTION_MAX_CHARS = 4000
MAX_FILES = 10
RATE_LIMITED_CODE = "feedback/rate-limited"  # the feedback module's error code
