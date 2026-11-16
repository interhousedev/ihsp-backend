"""Consent purposes, config stages, caseload names, new errors and app map."""

import json

from app.modules.admission.application.config import GetConfig
from app.modules.admission.application.privacy import LOCALES, describe_purposes
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.domain.errors import (
    AffordabilityGateError,
    ProofSourceError,
)
from app.modules.admission.ports.consent import PURPOSES
from app.settings import LimitsSettings
from app.settings_admission import AdmissionSettings
from app.shared.app_map import APP_MAP
from app.shared.i18n.core import I18nCore
from app.shared.limits import StaticLimits
from app.shared.paths import LOCALES_DIR
from tests.admission.unit.fakes import FakeStore, FakeUow

I18N = I18nCore(LOCALES_DIR).load()


def test_purposes_are_described_in_every_locale() -> None:
    out = describe_purposes(lambda lc, key: I18N.t(lc, key))
    assert [p["id"] for p in out] == list(PURPOSES)
    for p in out:
        for field in ("title", "text"):
            assert set(p[field]) == set(LOCALES)
            assert all(v and not v.startswith("admission-") for v in p[field].values())


def test_new_error_keys_exist_in_every_locale() -> None:
    for err in (AffordabilityGateError, ProofSourceError):
        for lc in LOCALES:
            path = LOCALES_DIR / lc / "admission.json"
            assert err.message_key in json.loads(path.read_text("utf-8"))


async def test_config_lists_the_stages() -> None:
    store = FakeStore()
    runtime = RuntimeSettingsService(lambda: FakeUow(store), ttl=0)
    cfg = await GetConfig(
        AdmissionSettings(), runtime, StaticLimits(LimitsSettings())
    ).execute()
    assert cfg.stages == ("setup", "words", "items", "chooser", "docs", "submitted")


def test_app_map_has_the_admission_pages() -> None:
    ids = {d.id for d in APP_MAP if d.app == "admission"}
    assert {
        "admission-chooser",
        "admission-documents",
        "admission-help",
        "admission-items",
        "admission-profile",
    } <= ids
    assert len({d.id for d in APP_MAP}) == len(APP_MAP)


async def test_config_workflow_options_equal_the_domain() -> None:
    from typing import get_args

    from app.modules.admission.domain import documents as docs
    from app.modules.admission.domain import workflow as wf

    store = FakeStore()
    runtime = RuntimeSettingsService(lambda: FakeUow(store), ttl=0)
    cfg = await GetConfig(
        AdmissionSettings(), runtime, StaticLimits(LimitsSettings())
    ).execute()
    w = cfg.workflow
    assert [k for k, _ in w.document_kinds] == list(get_args(wf.DocumentKind))
    assert {k for k, c in w.document_kinds if c} == set(wf.CONFIDENTIAL_KINDS)
    assert w.reject_reasons == docs.REJECT_REASON_CODES
    assert w.reminder_offsets == docs.REMINDER_OFFSETS
    assert w.reminder_channels == docs.REMINDER_CHANNELS
    assert w.deadline_statuses == get_args(docs.DeadlineStatus)
    assert [r for r, _ in w.rounds] == list(get_args(wf.Round))
    assert {r for r, b in w.rounds if b} == {"ED", "ED2"}
    assert w.buckets == get_args(wf.Label)
    assert w.milestone_kinds == docs.MILESTONE_KINDS
    assert w.affordability_statuses == get_args(wf.AffordabilityStatus)
    assert w.affordability_ack_statuses == ("gap", "unknown")
