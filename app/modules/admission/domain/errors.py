"""Errors of the admission module (stable codes `admission/*`)."""

from app.shared.base_error import (
    BaseError,
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)


class AdmissionNotFoundError(NotFoundError):
    """The object does not exist or the student is outside the actor's scope."""

    code = "admission/not_found"
    message_key = "admission-not-found"


class AdmissionForbiddenError(ForbiddenError):
    """In scope, but the actor lacks the permission. Params: permission."""

    code = "admission/forbidden"
    message_key = "admission-forbidden"


class NotEntitledError(ForbiddenError):
    """The user has no admission entitlement, staff role or help grant."""

    code = "admission/not_entitled"
    message_key = "admission-not-entitled"


class ConsentRequiredError(ForbiddenError):
    """A consent purpose is missing. Params: purpose."""

    code = "admission/consent_required"
    message_key = "admission-consent-required"


class GuardianConsentRequiredError(ForbiddenError):
    """A minor needs a guardian's consent for the purpose. Params: purpose."""

    code = "admission/guardian_consent_required"
    message_key = "admission-guardian-consent-required"


class CharLimitError(ValidationFailedError):
    """A text is longer than its limit. Params: field, limit."""

    code = "admission/char_limit"
    message_key = "admission-char-limit"


class WordsNotSetError(ValidationFailedError):
    """The three words must be confirmed first."""

    code = "admission/words_not_set"
    message_key = "admission-words-not-set"


class QuotaExceededError(RateLimitedError):
    """An AI quota is used up. Params: task, limit, period."""

    code = "admission/quota_exceeded"
    message_key = "admission-quota-exceeded"


class AffordabilityRequiredError(ValidationFailedError):
    """The list entry needs an affordability check or a sign-off first."""

    code = "admission/affordability_required"
    message_key = "admission-affordability-required"


class AffordabilityGateError(ValidationFailedError):
    """A binding round needs a clear affordability check. Params: institution."""

    code = "admission/affordability_gate"
    message_key = "admission-affordability-gate"


class EligibilityUnknownError(ValidationFailedError):
    """The eligibility of the qualification for this system is unknown."""

    code = "admission/eligibility_unknown"
    message_key = "admission-eligibility-unknown"


class InvalidProofUrlError(ValidationFailedError):
    """The proof URL is not an allowed public https address."""

    code = "admission/invalid_proof_url"
    message_key = "admission-invalid-proof-url"


class InvalidMediaUrlError(ValidationFailedError):
    """A logo or cover URL is not a plain https address."""

    code = "admission/invalid_media_url"
    message_key = "admission-invalid-media-url"


class ProofSourceError(ValidationFailedError):
    """A proof needs exactly one of link, file or pasted text."""

    code = "admission/proof_source"
    message_key = "admission-proof-source"


class GuestLinkLimitError(ValidationFailedError):
    """Too many active guest links, or a limit outside the allowed range."""

    code = "admission/guest_link_limit"
    message_key = "admission-guest-link-limit"


class SelfClaimError(ValidationFailedError):
    """A student cannot accept their own help request."""

    code = "admission/self_claim"
    message_key = "admission-self-claim"


class InvalidTransitionError(ConflictError):
    """The status change is not allowed from the current status. Params: status."""

    code = "admission/invalid_transition"
    message_key = "admission-invalid-transition"


class PickupNotSetError(ValidationFailedError):
    """The transcript officer has not set a pickup location."""

    code = "admission/pickup_not_set"
    message_key = "admission-pickup-not-set"


class UndoExpiredError(GoneError):
    """The undo window has passed."""

    code = "admission/undo_expired"
    message_key = "admission-undo-expired"


class AdmissionConflictError(ConflictError):
    """The row changed since it was read (`lock_version` mismatch)."""

    code = "admission/conflict"
    message_key = "admission-conflict"


class ScanPendingError(ConflictError):
    """The file is not ready to be used yet."""

    code = "admission/scan_pending"
    message_key = "admission-scan-pending"


class DelegationDeniedError(ForbiddenError):
    """The assignment exceeds what the grantor may delegate. Params: reason."""

    code = "admission/forbidden"
    message_key = "admission-delegation-denied"


class SavedViewLimitError(ValidationFailedError):
    """The user already has the maximum of saved views."""

    code = "admission/saved_view_limit"
    message_key = "admission-saved-view-limit"


class ItemLimitError(ValidationFailedError):
    """The student already has the maximum of items of a kind. Params: kind, limit."""

    code = "admission/item_limit"
    message_key = "admission-item-limit"


class ScoreInvalidError(ValidationFailedError):
    """A test score or definition is invalid. Params: field, min, max."""

    code = "admission/test_score_invalid"
    message_key = "admission-test-score-invalid"


class ItemIncompleteError(ValidationFailedError):
    """An item cannot be marked ready. Params: fields (the missing field names)."""

    code = "admission/item_incomplete"
    message_key = "admission-item-incomplete"


class ProjectedDateRequiredError(ValidationFailedError):
    """A planned number needs a target date. Params: field."""

    code = "admission/projected_date_required"
    message_key = "admission-projected-date-required"


class CalendarInputError(ValidationFailedError):
    """A calendar range or exam date is invalid. Params: field."""

    code = "admission/calendar_invalid"
    message_key = "admission-calendar-invalid"


ALL_ERRORS: tuple[type[BaseError], ...] = (
    AdmissionNotFoundError,
    AdmissionForbiddenError,
    NotEntitledError,
    ConsentRequiredError,
    GuardianConsentRequiredError,
    CharLimitError,
    ScoreInvalidError,
    WordsNotSetError,
    QuotaExceededError,
    AffordabilityRequiredError,
    AffordabilityGateError,
    EligibilityUnknownError,
    ProofSourceError,
    InvalidProofUrlError,
    InvalidMediaUrlError,
    GuestLinkLimitError,
    SelfClaimError,
    InvalidTransitionError,
    PickupNotSetError,
    UndoExpiredError,
    AdmissionConflictError,
    ScanPendingError,
    DelegationDeniedError,
    SavedViewLimitError,
    ItemLimitError,
    ItemIncompleteError,
    ProjectedDateRequiredError,
    CalendarInputError,
)


class InvalidAnswerError(ValidationFailedError):
    """An answer does not fit its question. Params: question."""

    code = "admission/invalid_answer"
    message_key = "admission-invalid-answer"


class ProfileIncompleteError(ValidationFailedError):
    """The background questions must be answered first."""

    code = "admission/profile_incomplete"
    message_key = "admission-profile-incomplete"


class VoiceTooLargeError(ValidationFailedError):
    """A voice recording is larger than the cap. Params: max_mb."""

    code = "admission/voice_too_large"
    message_key = "admission-voice-too-large"


class VoiceTooLongError(ValidationFailedError):
    """A voice recording is longer than the cap. Params: max_seconds."""

    code = "admission/voice_too_long"
    message_key = "admission-voice-too-long"


class VoiceFormatError(ValidationFailedError):
    """A voice recording is not a readable audio format. Params: formats."""

    code = "admission/voice_format"
    message_key = "admission-voice-format"


class ReadinessWeightsError(ValidationFailedError):
    """Weights must be non-negative numbers for known components, one above zero."""

    code = "admission/readiness_weights"
    message_key = "admission-readiness-weights"
