"""Apple Wallet pass of the student card: pass.json, images, manifest, signature.

A `.pkpass` is a ZIP archive. `manifest.json` maps every file to its SHA-1, and
`signature` is a detached PKCS#7 signature of the manifest made with the Pass
Type ID certificate; the Apple WWDR intermediate certificate goes with it.
"""

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.modules.identity.domain.student_card import WalletPass
from app.modules.identity.infrastructure.wallet.images import (
    emblem_png,
    fit_png,
    square_photo_png,
)

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import pkcs7

BACKGROUND = "rgb(15, 30, 61)"
FOREGROUND = "rgb(255, 255, 255)"
LABEL = "rgb(160, 176, 208)"

# Field labels are keys of the `<lang>.lproj/pass.strings` files.
LABELS: dict[str, dict[str, str]] = {
    "en": {
        "STUDENT": "STUDENT",
        "GROUP": "GROUP",
        "STUDENT_ID": "STUDENT ID",
        "SPECIALIZATION": "SPECIALIZATION",
        "ACADEMIC_YEAR": "ACADEMIC YEAR",
        "LYCEUM": "Lyceum",
        "VERIFY": "Check the card",
        "DESCRIPTION": "Student card",
    },
    "ru": {
        "STUDENT": "СТУДЕНТ",
        "GROUP": "ГРУППА",
        "STUDENT_ID": "ID СТУДЕНТА",
        "SPECIALIZATION": "СПЕЦИАЛЬНОСТЬ",
        "ACADEMIC_YEAR": "УЧЕБНЫЙ ГОД",
        "LYCEUM": "Лицей",
        "VERIFY": "Проверить билет",
        "DESCRIPTION": "Студенческий билет",
    },
    "uz": {
        "STUDENT": "TALABA",
        "GROUP": "GURUH",
        "STUDENT_ID": "TALABA ID",
        "SPECIALIZATION": "MUTAXASSISLIK",
        "ACADEMIC_YEAR": "OʻQUV YILI",
        "LYCEUM": "Litsey",
        "VERIFY": "Guvohnomani tekshirish",
        "DESCRIPTION": "Talabalik guvohnomasi",
    },
}

SigningKey = RSAPrivateKey | EllipticCurvePrivateKey


def _certificate(data: bytes) -> x509.Certificate:
    if b"-----BEGIN" in data:
        return x509.load_pem_x509_certificate(data)
    return x509.load_der_x509_certificate(data)


@dataclass(frozen=True, slots=True)
class ApplePassSigner:
    """The Pass Type ID certificate, its key and the WWDR certificate."""

    pass_type_id: str
    team_id: str
    certificate: x509.Certificate
    key: SigningKey
    wwdr: x509.Certificate

    @classmethod
    def from_files(
        cls,
        *,
        pass_type_id: str,
        team_id: str,
        cert_path: str,
        key_path: str,
        key_password: str | None,
        wwdr_path: str,
    ) -> "ApplePassSigner":
        """Load the certificates (PEM or DER) and the PEM private key."""
        key = serialization.load_pem_private_key(
            Path(key_path).read_bytes(),
            password=key_password.encode() if key_password else None,
        )
        if not isinstance(key, RSAPrivateKey | EllipticCurvePrivateKey):
            raise ValueError("the pass key must be an RSA or EC key")
        return cls(
            pass_type_id=pass_type_id,
            team_id=team_id,
            certificate=_certificate(Path(cert_path).read_bytes()),
            key=key,
            wwdr=_certificate(Path(wwdr_path).read_bytes()),
        )

    def sign(self, manifest: bytes) -> bytes:
        """Return the detached DER PKCS#7 signature of the manifest."""
        return (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(manifest)
            .add_signer(self.certificate, self.key, hashes.SHA256())
            .add_certificate(self.wwdr)
            .sign(
                serialization.Encoding.DER,
                [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary],
            )
        )


def _field(key: str, label: str, value: str) -> dict[str, str]:
    return {"key": key, "label": label, "value": value}


def pass_json(data: WalletPass, signer: ApplePassSigner) -> dict[str, Any]:
    """Return the pass.json of a generic pass."""
    card = data.card
    secondary = [_field("group", "GROUP", card.group or "—")]
    if card.student_id:
        secondary.append(_field("student_id", "STUDENT_ID", card.student_id))
    auxiliary = [_field("year", "ACADEMIC_YEAR", card.academic_year)]
    if card.speciality:
        auxiliary.insert(0, _field("speciality", "SPECIALIZATION", card.speciality))
    barcode: dict[str, str] = {
        "format": "PKBarcodeFormatQR",
        "message": data.verify_url,
        "messageEncoding": "iso-8859-1",
    }
    if card.student_id:
        barcode["altText"] = card.student_id
    return {
        "formatVersion": 1,
        "passTypeIdentifier": signer.pass_type_id,
        "teamIdentifier": signer.team_id,
        "serialNumber": data.serial,
        "organizationName": card.org_name,
        "description": "DESCRIPTION",
        "logoText": card.org_name,
        "backgroundColor": BACKGROUND,
        "foregroundColor": FOREGROUND,
        "labelColor": LABEL,
        "sharingProhibited": True,
        "generic": {
            "primaryFields": [_field("name", "STUDENT", card.full_name)],
            "secondaryFields": secondary,
            "auxiliaryFields": auxiliary,
            "backFields": [
                _field("lyceum", "LYCEUM", card.org_name),
                _field("verify", "VERIFY", data.verify_url),
            ],
        },
        "barcodes": [barcode],
    }


def _strings(labels: dict[str, str]) -> bytes:
    lines = [
        '"{}" = "{}";'.format(key, value.replace('"', '\\"'))
        for key, value in labels.items()
    ]
    return ("\n".join(lines) + "\n").encode("utf-16")


def pass_files(data: WalletPass, signer: ApplePassSigner) -> dict[str, bytes]:
    """Return every file of the pass except the manifest and the signature."""
    body = json.dumps(pass_json(data, signer), ensure_ascii=False)
    files = {"pass.json": body.encode()}
    for scale, suffix in ((1, ""), (2, "@2x"), (3, "@3x")):
        files[f"icon{suffix}.png"] = (
            fit_png(data.logo, 29 * scale, 29 * scale)
            if data.logo
            else emblem_png(29 * scale)
        )
        files[f"logo{suffix}.png"] = (
            fit_png(data.logo, 50 * scale, 50 * scale)
            if data.logo
            else emblem_png(50 * scale)
        )
        if data.photo:
            files[f"thumbnail{suffix}.png"] = square_photo_png(data.photo, 90 * scale)
    for lang, labels in LABELS.items():
        files[f"{lang}.lproj/pass.strings"] = _strings(labels)
    return files


def manifest(files: dict[str, bytes]) -> bytes:
    """Return manifest.json: the SHA-1 of every file."""
    digests = {name: hashlib.sha1(body).hexdigest() for name, body in files.items()}
    return json.dumps(digests, sort_keys=True).encode()


def build_pkpass(data: WalletPass, signer: ApplePassSigner) -> bytes:
    """Return the signed `.pkpass` archive."""
    files = pass_files(data, signer)
    manifest_bytes = manifest(files)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("signature", signer.sign(manifest_bytes))
    return out.getvalue()
