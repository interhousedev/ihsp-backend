"""The Apple Wallet pass: manifest of SHA-1s and a detached PKCS#7 signature."""

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.modules.identity.domain.student_card import StudentCard, WalletPass
from app.modules.identity.infrastructure.wallet.apple import (
    ApplePassSigner,
    build_pkpass,
)

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from PIL import Image


def _certificate(
    name: str, key: rsa.RSAPrivateKey, issuer_key: rsa.RSAPrivateKey, issuer: str
) -> x509.Certificate:
    now = datetime.now(UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(issuer_key, hashes.SHA256())
    )


def _signer() -> ApplePassSigner:
    wwdr_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pass_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wwdr = _certificate("Test WWDR", wwdr_key, wwdr_key, "Test WWDR")
    cert = _certificate("Pass Type ID: pass.test.card", pass_key, wwdr_key, "Test WWDR")
    return ApplePassSigner(
        pass_type_id="pass.test.card",
        team_id="TEAM123456",
        certificate=cert,
        key=pass_key,
        wwdr=wwdr,
    )


def _photo() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (120, 160), (200, 120, 80)).save(out, format="JPEG")
    return out.getvalue()


def _pass() -> WalletPass:
    card = StudentCard(
        first_name="Ali",
        last_name="Valiyev",
        middle_name="Akmalovich",
        student_id="4711",
        group="2TN2",
        course=2,
        academic_year="2026–2027",
        org_name="Academic Lyceum",
        lyceum_name=None,
        direction=None,
        speciality="Texnik-dasturchi",
        has_photo=True,
    )
    return WalletPass(
        serial="card-abc",
        card=card,
        verify_url="https://share.example/card/?t=token",
        photo=_photo(),
        logo=None,
        logo_url=None,
    )


def test_pkpass_has_manifest_of_every_file_and_a_valid_detached_signature() -> None:
    signer = _signer()
    archive = zipfile.ZipFile(io.BytesIO(build_pkpass(_pass(), signer)))
    names = set(archive.namelist())
    assert {"pass.json", "manifest.json", "signature", "icon.png", "logo.png"} <= names
    assert {
        "thumbnail@2x.png",
        "ru.lproj/pass.strings",
        "uz.lproj/pass.strings",
    } <= names

    manifest_bytes = archive.read("manifest.json")
    manifest = json.loads(manifest_bytes)
    assert set(manifest) == names - {"manifest.json", "signature"}
    for name, digest in manifest.items():
        assert hashlib.sha1(archive.read(name)).hexdigest() == digest

    body = json.loads(archive.read("pass.json"))
    assert body["passTypeIdentifier"] == "pass.test.card"
    assert body["teamIdentifier"] == "TEAM123456"
    assert body["generic"]["primaryFields"][0]["value"] == "Valiyev Ali Akmalovich"
    assert body["barcodes"][0]["message"] == "https://share.example/card/?t=token"
    assert body["barcodes"][0]["altText"] == "4711"

    signature = archive.read("signature")
    # The signer and the WWDR certificate travel inside the signature.
    embedded = pkcs7.load_der_pkcs7_certificates(signature)
    assert {c.subject.rfc4514_string() for c in embedded} == {
        signer.certificate.subject.rfc4514_string(),
        signer.wwdr.subject.rfc4514_string(),
    }
    # Detached: the manifest is not inside, and the signature verifies against it.
    assert manifest_bytes not in signature
    _verify_detached(signature, manifest_bytes, signer)


def _verify_detached(
    signature: bytes, manifest: bytes, signer: ApplePassSigner
) -> None:
    """Verify the CMS signer info: message digest and RSA over signed attributes."""
    from pyasn1.codec.der import decoder, encoder
    from pyasn1_modules import rfc5652

    info, _ = decoder.decode(signature, asn1Spec=rfc5652.ContentInfo())
    signed, _ = decoder.decode(info["content"], asn1Spec=rfc5652.SignedData())
    assert not signed["encapContentInfo"]["eContent"].hasValue()
    signer_info = signed["signerInfos"][0]
    attrs = signer_info["signedAttrs"]
    digests = [
        bytes(decoder.decode(a["attrValues"][0])[0])
        for a in attrs
        if a["attrType"] == rfc5652.id_messageDigest
    ]
    assert digests == [hashlib.sha256(manifest).digest()]
    as_set = rfc5652.SignedAttributes()
    for i, attr in enumerate(attrs):
        as_set[i] = attr
    public_key = signer.certificate.public_key()
    assert isinstance(public_key, rsa.RSAPublicKey)
    public_key.verify(
        bytes(signer_info["signature"]),
        encoder.encode(as_set),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_signer_loads_pem_files(tmp_path: Path) -> None:
    signer = _signer()
    cert = tmp_path / "pass.pem"
    key = tmp_path / "pass.key"
    wwdr = tmp_path / "wwdr.cer"
    cert.write_bytes(signer.certificate.public_bytes(serialization.Encoding.PEM))
    wwdr.write_bytes(signer.wwdr.public_bytes(serialization.Encoding.DER))
    key.write_bytes(
        signer.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"secret"),
        )
    )
    loaded = ApplePassSigner.from_files(
        pass_type_id="pass.test.card",
        team_id="TEAM123456",
        cert_path=str(cert),
        key_path=str(key),
        key_password="secret",
        wwdr_path=str(wwdr),
    )
    assert loaded.certificate == signer.certificate
    assert loaded.wwdr == signer.wwdr
