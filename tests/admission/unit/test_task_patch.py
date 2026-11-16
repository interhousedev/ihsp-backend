"""PATCH /tasks: null on a required field leaves it unchanged."""

import datetime as dt

from app.interfaces.http.v1.admission.routes_tasks import TaskPatch, patch_changes


def test_null_required_fields_are_dropped_and_dates_stay_clearable() -> None:
    body = TaskPatch.model_validate(
        {
            "lock_version": 1,
            "title": None,
            "description": None,
            "status": None,
            "priority": None,
            "deadline": None,
        }
    )
    assert patch_changes(body) == {"deadline": None}


def test_set_fields_pass_through() -> None:
    body = TaskPatch.model_validate(
        {"lock_version": 1, "title": "New", "start_date": "2026-01-02"}
    )
    assert patch_changes(body) == {"title": "New", "start_date": dt.date(2026, 1, 2)}
