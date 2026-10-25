"""Console logs (development) print an exception instead of failing to format it."""

import logging

from app.shared.logging import configure_logging

import pytest
import structlog


def test_console_renderer_prints_exceptions(capsys: pytest.CaptureFixture[str]) -> None:
    """A logged exception shows its traceback in development mode."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("INFO", json_logs=False)
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger("taskiq.test").exception("task failed")
        captured = capsys.readouterr()
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        structlog.reset_defaults()

    assert "task failed" in captured.out
    assert "ValueError" in captured.out
    assert "Logging error" not in captured.err
