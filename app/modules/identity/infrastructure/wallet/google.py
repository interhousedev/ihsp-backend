"""Google Wallet "save" link of the student card: a generic pass in a signed JWT.

The JWT carries the pass class and object; Google creates them on save. It is
signed with RS256 by the issuer's service account.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.modules.identity.domain.student_card import WalletPass

from joserfc import jwt
from joserfc.jwk import RSAKey

SAVE_URL = "https://pay.google.com/gp/v/save/"
BACKGROUND = "#0f1e3d"

LABELS: dict[str, dict[str, str]] = {
    "student": {"en": "STUDENT", "ru": "СТУДЕНТ", "uz": "TALABA"},
    "group": {"en": "GROUP", "ru": "ГРУППА", "uz": "GURUH"},
    "student_id": {"en": "STUDENT ID", "ru": "ID СТУДЕНТА", "uz": "TALABA ID"},
    "speciality": {
        "en": "SPECIALIZATION",
        "ru": "СПЕЦИАЛЬНОСТЬ",
        "uz": "MUTAXASSISLIK",
    },
    "year": {"en": "ACADEMIC YEAR", "ru": "УЧЕБНЫЙ ГОД", "uz": "OʻQUV YILI"},
}


def _localized(key: str) -> dict[str, Any]:
    values = LABELS[key]
    return {
        "defaultValue": {"language": "en", "value": values["en"]},
        "translatedValues": [
            {"language": lang, "value": values[lang]} for lang in ("ru", "uz")
        ],
    }


def _plain(value: str) -> dict[str, Any]:
    return {"defaultValue": {"language": "en", "value": value}}


@dataclass(frozen=True, slots=True)
class GoogleWalletIssuer:
    """The issuer id and the service account that signs the save links."""

    issuer_id: str
    class_suffix: str
    client_email: str
    key: RSAKey
    key_id: str | None

    @classmethod
    def from_file(
        cls, *, issuer_id: str, class_suffix: str, service_account_path: str
    ) -> "GoogleWalletIssuer":
        """Read the service-account JSON key file."""
        account = json.loads(Path(service_account_path).read_text())
        return cls(
            issuer_id=issuer_id,
            class_suffix=class_suffix,
            client_email=account["client_email"],
            key=RSAKey.import_key(account["private_key"]),
            key_id=account.get("private_key_id"),
        )

    def generic_object(self, data: WalletPass) -> dict[str, Any]:
        """Return the generic pass object of a card."""
        card = data.card
        # A new QR token gives a new object: Google keeps saved objects as they were.
        digest = hashlib.sha256(data.verify_url.encode()).hexdigest()[:24]
        modules = [("group", card.group or "—")]
        if card.student_id:
            modules.append(("student_id", card.student_id))
        if card.speciality:
            modules.append(("speciality", card.speciality))
        modules.append(("year", card.academic_year))
        barcode: dict[str, Any] = {"type": "QR_CODE", "value": data.verify_url}
        if card.student_id:
            barcode["alternateText"] = card.student_id
        obj: dict[str, Any] = {
            "id": f"{self.issuer_id}.{data.serial}-{digest}",
            "classId": f"{self.issuer_id}.{self.class_suffix}",
            "state": "ACTIVE",
            "hexBackgroundColor": BACKGROUND,
            "cardTitle": _plain(card.org_name),
            "subheader": _localized("student"),
            "header": _plain(card.full_name),
            "textModulesData": [
                {
                    "id": key,
                    "localizedHeader": _localized(key),
                    "body": value,
                }
                for key, value in modules
            ],
            "barcode": barcode,
        }
        if data.logo_url:
            obj["logo"] = {
                "sourceUri": {"uri": data.logo_url},
                "contentDescription": _plain(card.org_name),
            }
        return obj

    def save_url(self, data: WalletPass, origins: list[str]) -> str:
        """Return the "Add to Google Wallet" link."""
        claims = {
            "iss": self.client_email,
            "aud": "google",
            "typ": "savetowallet",
            "origins": origins,
            "payload": {
                "genericClasses": [{"id": f"{self.issuer_id}.{self.class_suffix}"}],
                "genericObjects": [self.generic_object(data)],
            },
        }
        header: dict[str, Any] = {"alg": "RS256", "typ": "JWT"}
        if self.key_id:
            header["kid"] = self.key_id
        return SAVE_URL + jwt.encode(header, claims, self.key)
