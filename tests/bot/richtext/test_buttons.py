"""Inline keyboard button markup: url and callback validation."""

from app.interfaces.bot.richtext.buttons import callback_data_fits, parse_button_body


def test_https_target_becomes_url_button() -> None:
    spec = parse_button_body("Открыть|https://iht.uz/a")

    assert spec is not None
    assert spec.url == "https://iht.uz/a"
    assert spec.callback_data is None


def test_http_target_is_rejected() -> None:
    assert parse_button_body("Открыть|http://iht.uz") is None


def test_javascript_target_is_rejected() -> None:
    assert parse_button_body("Открыть|javascript:alert(1)") is None


def test_plain_target_becomes_callback_button() -> None:
    spec = parse_button_body("Ок|ok:1")

    assert spec is not None
    assert spec.callback_data == "ok:1"
    assert spec.url is None


def test_callback_of_exactly_64_bytes_is_accepted() -> None:
    assert callback_data_fits("a" * 64) is True


def test_callback_of_65_bytes_is_rejected() -> None:
    assert callback_data_fits("a" * 65) is False


def test_callback_limit_counts_utf8_bytes() -> None:
    assert callback_data_fits("я" * 32) is True
    assert callback_data_fits("я" * 33) is False


def test_body_without_separator_is_rejected() -> None:
    assert parse_button_body("только метка") is None


def test_empty_label_is_rejected() -> None:
    assert parse_button_body("  |ok:1") is None
