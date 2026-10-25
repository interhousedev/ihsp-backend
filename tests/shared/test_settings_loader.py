"""Layered env files, start-up errors and unknown variables."""

from pathlib import Path

from app.settings_loader import (
    SettingsError,
    describe,
    load_settings,
    parse_env_files,
    setting_exists,
    unknown_variables,
    variable_name,
)

import pytest
from pydantic import BaseModel, ValidationError
from structlog.testing import capture_logs


def write(path: Path, text: str) -> Path:
    """Write an env file and return its path."""
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the variables a test sets are visible (IHSP_ENV=test stays)."""
    monkeypatch.delenv("IHSP_ENV_FILE", raising=False)


# - - - IHSP_ENV_FILE as a comma list - - -


def test_the_env_file_variable_is_a_comma_list_in_reading_order(tmp_path: Path) -> None:
    """Spaces around names are ignored; empty items too."""
    first = write(tmp_path / "base.env", "IHSP_LOG_LEVEL=INFO\n")
    second = write(tmp_path / "local.env", "IHSP_LOG_LEVEL=DEBUG\n")

    files = parse_env_files(f" {first} , ,{second}")

    assert files == [first, second]


def test_no_env_file_means_no_files() -> None:
    """Unset and empty values read nothing."""
    assert parse_env_files(None) == [] and parse_env_files("") == []


def test_a_missing_required_file_stops_the_start(tmp_path: Path) -> None:
    """A typo in a path must not silently start with defaults."""
    present = write(tmp_path / "base.env", "")

    with pytest.raises(SettingsError, match="file not found: .*nope.env"):
        parse_env_files(f"{present},{tmp_path / 'nope.env'}")


def test_a_question_mark_makes_a_file_optional(tmp_path: Path) -> None:
    """`?name` is skipped when it does not exist and read when it does."""
    base = write(tmp_path / "base.env", "")
    optional = tmp_path / "local.env"

    assert parse_env_files(f"{base},?{optional}") == [base]
    write(optional, "")
    assert parse_env_files(f"{base},?{optional}") == [base, optional]


def test_later_files_override_earlier_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A base file is merged with overrides; keys only in one file survive."""
    base = write(
        tmp_path / "base.env",
        "IHSP_LOG_LEVEL=INFO\n"
        "IHSP_DATABASE__POOL_SIZE=5\n"
        "IHSP_AI__DEFAULT__MODEL=base/model\n"
        "IHSP_AI__TASKS__STUDIO_QUIZ__MODEL=base/quiz\n",
    )
    local = write(
        tmp_path / "local.env",
        "IHSP_LOG_LEVEL=DEBUG\n"
        "IHSP_AI__TASKS__STUDIO_QUIZ__MODEL=local/quiz\n"
        "IHSP_AI__TASKS__STUDIO_QUIZ__TEMPERATURE=0.4\n",
    )
    monkeypatch.setenv("IHSP_ENV_FILE", f"{base},{local}")

    settings = load_settings()

    assert settings.log_level == "DEBUG"
    assert settings.database.pool_size == 5
    assert settings.ai.default.model == "base/model"
    quiz = settings.ai.tasks["studio_quiz"]  # type: ignore[index]
    assert (quiz.model, quiz.temperature) == ("local/quiz", 0.4)


def test_the_process_environment_beats_every_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Precedence: process environment, last file, earlier files, defaults."""
    base = write(tmp_path / "base.env", "IHSP_LOG_LEVEL=INFO\n")
    local = write(tmp_path / "local.env", "IHSP_LOG_LEVEL=DEBUG\n")
    monkeypatch.setenv("IHSP_ENV_FILE", f"{base},{local}")
    monkeypatch.setenv("IHSP_LOG_LEVEL", "ERROR")

    assert load_settings().log_level == "ERROR"


def test_a_single_file_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old form: IHSP_ENV_FILE=<one path>."""
    only = write(tmp_path / "only.env", "IHSP_LOG_LEVEL=WARNING\n")
    monkeypatch.setenv("IHSP_ENV_FILE", str(only))

    assert load_settings().log_level == "WARNING"


# - - - clear errors - - -


def test_every_bad_variable_is_listed_with_its_name_and_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One line per variable, in the environment's spelling."""
    bad = write(
        tmp_path / "bad.env",
        "IHSP_DATABASE__POOL_SIZE=many\n"
        "IHSP_AI__DEFAULT__TEMPERATURE=hot\n"
        "IHSP_FEATURES__NOTEBOOKS=maybe\n",
    )
    monkeypatch.setenv("IHSP_ENV_FILE", str(bad))

    with pytest.raises(SettingsError) as caught:
        load_settings()

    message = str(caught.value)
    assert message.startswith("invalid settings (3):")
    assert "IHSP_DATABASE__POOL_SIZE: " in message and "(got 'many')" in message
    assert "IHSP_AI__DEFAULT__TEMPERATURE: " in message
    assert "IHSP_FEATURES__NOTEBOOKS: " in message


def test_the_error_is_a_value_error() -> None:
    """Callers that catch ValueError keep working."""
    assert issubclass(SettingsError, ValueError)


def test_secret_values_are_not_echoed() -> None:
    """A bad value of a key, token, secret or password is named, never printed."""

    class Credentials(BaseModel):
        api_key: int
        port: int

    with pytest.raises(ValidationError) as caught:
        Credentials(api_key="sekret-value", port="not-a-port")  # type: ignore[arg-type]

    text = describe(caught.value)
    assert "IHSP_API_KEY: " in text and "sekret-value" not in text
    assert "(got 'not-a-port')" in text


def test_production_problems_are_reported_without_a_variable_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production guard lists what is missing, as before."""
    monkeypatch.setenv("IHSP_ENV", "prod")

    with pytest.raises(SettingsError, match="production settings missing"):
        load_settings()


def test_variable_names_come_from_error_locations() -> None:
    """('ai', 'tasks', 'x', '[key]') is the variable IHSP_AI__TASKS__X."""
    assert variable_name(("ai", "tasks", "x", "[key]")) == "IHSP_AI__TASKS__X"
    assert variable_name(("database", "pool_size")) == "IHSP_DATABASE__POOL_SIZE"


def test_describe_counts_the_problems() -> None:
    """The header says how many variables are wrong."""
    from app.settings import DatabaseSettings

    with pytest.raises(ValidationError) as caught:
        DatabaseSettings(pool_size="many")  # type: ignore[arg-type]

    assert describe(caught.value).startswith("invalid settings (1):")


# - - - unknown variables - - -


def test_setting_exists_follows_sections_and_dict_keys() -> None:
    """Typos in a section, a field or a task name are not settings."""
    assert setting_exists("IHSP_ENV")
    assert setting_exists("IHSP_DATABASE__POOL_SIZE")
    assert setting_exists("IHSP_AI__TASKS__STUDIO_QUIZ__MODEL")
    assert setting_exists("IHSP_AI__TASKS__STUDIO_QUIZ")
    assert not setting_exists("IHSP_AI__TASKS__STUDIO_QUIZZ__MODEL")
    assert not setting_exists("IHSP_AI__TASKS__STUDIO_QUIZ__NAME")
    assert not setting_exists("IHSP_DATABASE__POOL")
    assert not setting_exists("IHSP_DATABASE__URL__X")
    assert not setting_exists("OTHER_ENV")


def test_unknown_variables_skip_the_ones_other_code_reads() -> None:
    """IHSP_ENV_FILE, the web build and the Hydra Mini App client are not typos."""
    names = [
        "IHSP_ENV_FILE",
        "IHSP_WEB_API_URL",
        "IHSP_HYDRA__MINIAPP_CLIENT_ID",
        "IHSP_BOT_USERNAME",
        "IHSP_AI__DEFAULT__MODELL",
        "ihsp_log_levl",
        "PATH",
    ]

    assert unknown_variables(names) == ["IHSP_AI__DEFAULT__MODELL", "IHSP_LOG_LEVL"]


def test_loading_warns_about_a_misspelled_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo in a file or the environment is logged, not fatal."""
    typo = write(tmp_path / "typo.env", "IHSP_AI__TASKS__STUDIO_QUIZ__MODLE=x\n")
    monkeypatch.setenv("IHSP_ENV_FILE", str(typo))
    monkeypatch.setenv("IHSP_FEATURES__NOTEBOOK", "false")

    with capture_logs() as logs:
        load_settings()

    warning = [log for log in logs if log["event"] == "settings.unknown_variables"]
    assert len(warning) == 1
    assert warning[0]["variables"] == [
        "IHSP_AI__TASKS__STUDIO_QUIZ__MODLE",
        "IHSP_FEATURES__NOTEBOOK",
    ]


def test_a_clean_environment_logs_no_warning() -> None:
    """Only the test environment variable is set."""
    with capture_logs() as logs:
        load_settings()

    assert [log for log in logs if log["event"].startswith("settings.")] == []


def test_the_cli_prints_the_bad_variables_and_exits_with_a_config_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`python -m app <process>` shows the list, not a traceback."""
    from app import __main__ as cli

    monkeypatch.setenv("IHSP_AI__DEFAULT__TEMPERATURE", "hot")
    monkeypatch.setenv("IHSP_DATABASE__POOL_SIZE", "many")

    code = cli.main(["migrate"])

    assert code == cli.BAD_SETTINGS_EXIT_CODE
    err = capsys.readouterr().err
    assert "invalid settings (2):" in err
    assert "IHSP_AI__DEFAULT__TEMPERATURE" in err and "IHSP_DATABASE__POOL_SIZE" in err
