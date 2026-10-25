"""VAPID key generation, the script and the factory that builds the sender."""

import base64
import importlib.util
from pathlib import Path

from app.modules.notify.infrastructure.push_sender_factory import make_push_sender
from app.modules.notify.infrastructure.pywebpush_sender import PywebpushSender
from app.modules.notify.infrastructure.vapid import (
    generate_vapid_keys,
    load_private_key,
    public_key_of,
)
from app.settings import PushSettings
from app.shared.paths import BACKEND_ROOT

import pytest
from pydantic import SecretStr, ValidationError


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def test_generated_keys_have_the_shape_browsers_expect() -> None:
    """The public key is a 65-byte point; the private key a 32-byte scalar."""
    keys = generate_vapid_keys()

    assert len(_unb64(keys.public_key)) == 65 and _unb64(keys.public_key)[0] == 4
    assert len(_unb64(keys.private_key)) == 32
    assert "=" not in keys.public_key + keys.private_key


def test_the_private_key_gives_back_the_public_key() -> None:
    """Round trip: what the server signs with matches what browsers got."""
    keys = generate_vapid_keys()

    assert public_key_of(load_private_key(keys.private_key)) == keys.public_key


def test_each_call_makes_a_new_pair() -> None:
    """Keys are random."""
    assert generate_vapid_keys().private_key != generate_vapid_keys().private_key


def _script() -> object:
    spec = importlib.util.spec_from_file_location(
        "gen_vapid", BACKEND_ROOT / "scripts" / "gen_vapid.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_prints_the_three_settings(capsys: pytest.CaptureFixture[str]) -> None:
    """The output is a valid env file."""
    assert _script().main([]) == 0  # type: ignore[attr-defined]

    lines = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
    assert lines["IHSP_PUSH__ENABLED"] == "true"
    settings = PushSettings(
        enabled=True,
        vapid_public_key=lines["IHSP_PUSH__VAPID_PUBLIC_KEY"],
        vapid_private_key=SecretStr(lines["IHSP_PUSH__VAPID_PRIVATE_KEY"]),
    )
    sender, closer = make_push_sender(settings)
    assert isinstance(sender, PywebpushSender) and closer is not None


def test_script_writes_a_private_file_and_keeps_it_on_the_next_run(
    tmp_path: Path,
) -> None:
    """scripts/dev.sh runs this on every start; the pair must stay the same."""
    target = tmp_path / "keys" / "vapid.env"
    script = _script()

    script.main(["--out", str(target)])  # type: ignore[attr-defined]
    first = target.read_text()
    script.main(["--out", str(target)])  # type: ignore[attr-defined]

    assert target.read_text() == first
    assert target.stat().st_mode & 0o777 == 0o600
    script.main(["--out", str(target), "--force"])  # type: ignore[attr-defined]
    assert target.read_text() != first


def test_push_off_builds_no_sender() -> None:
    """PUSH__ENABLED=false: the dispatcher has no push channel."""
    assert make_push_sender(PushSettings()) == (None, None)


def test_enabled_push_needs_both_keys() -> None:
    """A half-configured push fails at startup, not at the first notification."""
    with pytest.raises(ValidationError, match="PUSH__ENABLED needs"):
        PushSettings(enabled=True, vapid_public_key="abc")


def test_subject_must_be_a_mailto_or_https_url() -> None:
    """Push services reject other contact forms."""
    keys = generate_vapid_keys()

    with pytest.raises(ValidationError, match="PUSH__SUBJECT"):
        PushSettings(
            enabled=True,
            vapid_public_key=keys.public_key,
            vapid_private_key=SecretStr(keys.private_key),
            subject="ops@ihsu.uz",
        )


def test_a_public_key_from_another_pair_is_refused() -> None:
    """Browsers subscribe with one key; signing with another would fail silently."""
    one, other = generate_vapid_keys(), generate_vapid_keys()
    settings = PushSettings(
        enabled=True,
        vapid_public_key=one.public_key,
        vapid_private_key=SecretStr(other.private_key),
    )

    with pytest.raises(ValueError, match="does not match"):
        make_push_sender(settings)


def test_empty_environment_values_mean_not_set() -> None:
    """`IHSP_PUSH__VAPID_PUBLIC_KEY=` in .env.sample."""
    settings = PushSettings.model_validate(
        {"vapid_public_key": "", "vapid_private_key": ""}
    )

    assert settings.vapid_public_key is None and settings.vapid_private_key is None
