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


class CatalogFactInvalidError(ValidationFailedError):
    """A proposed catalog fact is not valid. Params: fact, reason."""

    code = "admission/catalog_fact_invalid"
    message_key = "admission-catalog-fact-invalid"


class CatalogDuplicateError(ConflictError):
    """The school or a pending proposal exists. Params: institution_id, proposal_id."""

    code = "admission/catalog_duplicate"
    message_key = "admission-catalog-duplicate"


class CatalogProposalLimitError(RateLimitedError):
    """Too many catalog proposals today. Params: limit."""

    code = "admission/catalog_proposal_limit"
    message_key = "admission-catalog-proposal-limit"


class EssayTooShortError(ValidationFailedError):
    """The essay is too short to check. Params: min, count."""

    code = "admission/essay_too_short"
    message_key = "admission-essay-too-short"


class EssayVaultUnavailableError(BaseError):
    """The essay key service is unreachable; essays stay sealed (fail closed)."""

    code = "admission/essay_vault_unavailable"
    status = 503
    message_key = "admission-essay-vault-unavailable"


class EssayKeyUnavailableError(BaseError):
    """A student's essay key is gone while sealed text exists (fail closed)."""

    code = "admission/essay_key_unavailable"
    status = 503
    message_key = "admission-essay-key-unavailable"


class CatalogCycleError(ValidationFailedError):
    """A proposal names a cycle other than the current or next one. Params: cycle."""

    code = "admission/catalog_cycle"
    message_key = "admission-catalog-cycle"


class InviteNotFoundError(NotFoundError):
    """The review link is unknown, expired or revoked (one answer for all)."""

    code = "admission/invite_not_found"
    message_key = "admission-invite-not-found"


class InviteLimitError(ValidationFailedError):
    """Too many active review links on one essay. Params: limit."""

    code = "admission/invite_limit"
    message_key = "admission-invite-limit"


class ExemplarInvalidError(ValidationFailedError):
    """An exemplar essay field is not valid. Params: field, reason."""

    code = "admission/exemplar_invalid"
    message_key = "admission-exemplar-invalid"


class ExemplarDuplicateError(ConflictError):
    """The exemplar essay is already in the library. Params: exemplar_id."""

    code = "admission/exemplar_duplicate"
    message_key = "admission-exemplar-duplicate"


class KbBodyInvalidError(ValidationFailedError):
    """An FAQ article body breaks the rich-content rules. Params: reason."""

    code = "admission/kb_body_invalid"
    message_key = "admission-kb-body-invalid"
