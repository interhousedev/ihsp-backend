"""ID-19: our signed assertions for Hydra's JWT-bearer grant."""

from datetime import timedelta

from app.modules.identity.infrastructure.jwt_assertion import JoseAssertionSigner
from app.settings import Settings
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

from joserfc import jwt
from joserfc.jwk import RSAKey


def signer(
    settings: Settings, clock: FixedClock, key_id: str = "k1"
) -> JoseAssertionSigner:
    """A signer with the settings' key."""
    return JoseAssertionSigner(
        private_key_pem=settings.jwt_bearer.private_key_pem.get_secret_value(),
        key_id=key_id,
        issuer="ihsp-identity",
        token_url="http://localhost:4444/oauth2/token",
        clock=clock,
    )


def test_assertion_has_the_claims_hydra_requires(
    settings: Settings, clock: FixedClock
) -> None:
    """hydra.md 11.2: iss, sub, aud (token URL), exp, iat, jti, kid in the header."""
    sub, sid = new_id(), new_id()

    token = signer(settings, clock).sign(sub, sid, ["tg"])

    decoded = jwt.decode(token, RSAKey.import_key(signer(settings, clock).public_jwk()))
    claims = decoded.claims
    assert decoded.header["kid"] == "k1"
    assert decoded.header["alg"] == "RS256"
    assert claims["iss"] == "ihsp-identity"
    assert claims["sub"] == str(sub)
    assert claims["aud"] == "http://localhost:4444/oauth2/token"
    assert claims["exp"] - claims["iat"] == 300
    assert claims["jti"]
    assert (claims["sid"], claims["amr"]) == (str(sid), ["tg"])


def test_each_assertion_has_its_own_jti(settings: Settings, clock: FixedClock) -> None:
    """Hydra rejects a reused jti."""
    s = signer(settings, clock)
    sub, sid = new_id(), new_id()

    first = jwt.decode(s.sign(sub, sid, ["tg"]), RSAKey.import_key(s.public_jwk()))
    second = jwt.decode(s.sign(sub, sid, ["tg"]), RSAKey.import_key(s.public_jwk()))

    assert first.claims["jti"] != second.claims["jti"]


def test_read_returns_the_claims_of_our_own_assertion(
    settings: Settings, clock: FixedClock
) -> None:
    """The token hook reads sid and amr from assertions it can verify."""
    s = signer(settings, clock)
    sub, sid = new_id(), new_id()

    claims = s.read(s.sign(sub, sid, ["tg"]))

    assert claims is not None
    assert (claims.user_id, claims.session_id, claims.amr) == (sub, sid, ("tg",))


def test_read_refuses_foreign_or_broken_assertions(
    settings: Settings, clock: FixedClock
) -> None:
    """Only our key counts."""
    s = signer(settings, clock)
    foreign = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    forged = jwt.encode(
        {"alg": "RS256", "kid": "k1"},
        {"iss": "ihsp-identity", "sub": str(new_id()), "sid": str(new_id())},
        foreign,
    )

    assert s.read(forged) is None
    assert s.read("garbage") is None
    assert timedelta(minutes=5).total_seconds() == 300
