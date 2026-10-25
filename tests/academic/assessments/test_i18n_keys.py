"""Every message key the assessments area uses exists in uz, ru and en."""

import inspect
import json
from types import ModuleType

from app.modules.academic.domain.assessments import errors
from app.modules.academic.domain.marks import errors as marks_errors
from app.shared.base_error import BaseError
from app.shared.paths import LOCALES_DIR

LANGUAGES = ("en", "ru", "uz")


def _messages(lang: str, name: str) -> dict[str, str]:
    path = LOCALES_DIR / lang / f"{name}.json"
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _keys(module: ModuleType) -> set[str]:
    return {
        cls.message_key
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, BaseError) and cls.__module__ == module.__name__
    }


def test_every_assessment_error_has_a_translation_in_every_language() -> None:
    """CODESTYLE: i18n keys added for all three languages."""
    keys = _keys(errors)

    assert "academic-not-head-student" in keys
    for lang in LANGUAGES:
        missing = keys - set(_messages(lang, "academic_assessments"))
        assert not missing, f"{lang}: {sorted(missing)}"


def test_the_planner_error_and_the_control_week_error_are_translated() -> None:
    """The what-if and the term control periods have messages too."""
    for lang in LANGUAGES:
        assert marks_errors.InvalidWhatIfError.message_key in _messages(
            lang, "academic_marks"
        )
        assert "academic-term-control-periods-invalid" in _messages(
            lang, "academic_schedule"
        )


def test_the_three_languages_have_the_same_assessment_keys() -> None:
    """No key is translated into one language only."""
    en = set(_messages("en", "academic_assessments"))

    assert set(_messages("ru", "academic_assessments")) == en
    assert set(_messages("uz", "academic_assessments")) == en
    assert all(key.startswith("academic-") for key in en)


def test_the_reminder_texts_exist_in_every_language() -> None:
    """notify-assessment-* keys come in all languages with the same placeholders."""
    en = {k: v for k, v in _messages("en", "notify").items() if "assessment" in k}

    assert en
    for lang in ("ru", "uz"):
        other = _messages(lang, "notify")
        assert set(en) <= set(other)
        for key, text in en.items():
            for name in (
                "label",
                "when",
                "subject",
                "date",
                "start",
                "end",
                "time",
                "room",
            ):
                assert ("{%s}" % name in text) == ("{%s}" % name in other[key]), key
