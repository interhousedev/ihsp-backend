"""Password rules (ID-10): length and character classes."""

MIN_LENGTH = 8


def check_password(value: str) -> list[str]:
    """Return i18n error keys for every broken rule; empty means acceptable."""
    errors: list[str] = []
    if len(value) < MIN_LENGTH:
        errors.append("id-password-too-short")
    if not any(ch.isdigit() for ch in value):
        errors.append("id-password-no-digit")
    if not any(ch.isupper() for ch in value):
        errors.append("id-password-no-upper")
    if not any(ch.islower() for ch in value):
        errors.append("id-password-no-lower")
    return errors
