"""Limits shared by the recovery confirm steps (password reset, OTP reset)."""

from app.modules.identity.domain.errors import OtpInvalidError
from app.modules.identity.ports.login_throttle import LoginThrottle
from app.shared.rate_limit import RateLimiter

CONFIRMS_PER_LOGIN_PER_HOUR = 15


async def limit_confirms(rate_limiter: RateLimiter, login: str) -> None:
    """Bound the guesses against one login across IPs (RateLimitedError when over)."""
    key = f"recovery-login:{login.strip().lower()}"
    await rate_limiter.hit(key, limit=CONFIRMS_PER_LOGIN_PER_HOUR, window_seconds=3600)


async def code_failure(
    throttle: LoginThrottle, purpose: str, login: str, ip: str
) -> OtpInvalidError:
    """The error for a wrong code; ``attempts_left`` does not depend on the account."""
    left = await throttle.record_code_failure(purpose, login, ip)
    return OtpInvalidError(params={"attempts_left": left})
