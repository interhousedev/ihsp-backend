"""WebAuthn relying party of IHT ID over py_webauthn."""

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.modules.identity.domain.errors import PasskeyInvalidError
from app.modules.identity.ports.webauthn import (
    CeremonyOptions,
    RegisteredCredential,
    VerifiedAssertion,
)

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

RP_NAME = "IHT ID"
_KNOWN_TRANSPORTS = {t.value for t in AuthenticatorTransport}


@dataclass(frozen=True, slots=True)
class PyWebAuthn:
    """RP id is the host of the IHT ID URL; the origin is that URL's origin."""

    rp_id: str
    origin: str

    @classmethod
    def for_url(cls, id_url: str) -> "PyWebAuthn":
        """``https://id.example.uz/...`` gives rp_id ``id.example.uz``."""
        parts = urlsplit(id_url)
        return cls(
            rp_id=parts.hostname or "localhost",
            origin=f"{parts.scheme}://{parts.netloc}",
        )

    def registration_options(
        self,
        *,
        user_id: bytes,
        user_name: str,
        display_name: str,
        exclude: list[bytes],
    ) -> CeremonyOptions:
        """Discoverable credential, user verification required, no attestation."""
        options = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=RP_NAME,
            user_id=user_id,
            user_name=user_name,
            user_display_name=display_name,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=i) for i in exclude],
        )
        return CeremonyOptions(
            options=json.loads(options_to_json(options)), challenge=options.challenge
        )

    def verify_registration(
        self, credential: dict[str, Any], challenge: bytes
    ) -> RegisteredCredential:
        """Raise PasskeyInvalidError on any failure."""
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origin,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
            raise PasskeyInvalidError(params={"reason": type(exc).__name__}) from exc
        response = credential.get("response") or {}
        transports = [
            str(t) for t in response.get("transports") or [] if t in _KNOWN_TRANSPORTS
        ]
        return RegisteredCredential(
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=transports,
            backed_up=verified.credential_backed_up,
        )

    def authentication_options(self) -> CeremonyOptions:
        """Empty allow list: the browser offers every passkey of this site."""
        options = generate_authentication_options(
            rp_id=self.rp_id, user_verification=UserVerificationRequirement.REQUIRED
        )
        return CeremonyOptions(
            options=json.loads(options_to_json(options)), challenge=options.challenge
        )

    def verify_authentication(
        self,
        credential: dict[str, Any],
        challenge: bytes,
        *,
        public_key: bytes,
        sign_count: int,
    ) -> VerifiedAssertion:
        """Raise PasskeyInvalidError on any failure."""
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origin,
                credential_public_key=public_key,
                credential_current_sign_count=sign_count,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
            raise PasskeyInvalidError(params={"reason": type(exc).__name__}) from exc
        return VerifiedAssertion(
            new_sign_count=verified.new_sign_count,
            backed_up=verified.credential_backed_up,
        )
