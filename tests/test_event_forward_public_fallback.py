from __future__ import annotations

import json

from providers.event_forward import build_configured_event_forward_provider
from providers.public_decision_information import PublicDecisionInformationProvider


def test_event_forward_uses_strict_public_provider_when_no_configured_dataset(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "public-live-information-records.json"
    path.write_text(json.dumps({"records": []}), encoding="utf-8")
    monkeypatch.delenv(
        "CAPITAL_INTELLIGENCE_DECISION_INFORMATION_DATASET_BINDING",
        raising=False,
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_CERTIFIED_PUBLIC_DECISION_INFORMATION_RECORDS",
        str(path),
    )
    provider = build_configured_event_forward_provider()
    assert isinstance(provider, PublicDecisionInformationProvider)
    assert provider.records(
        start_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        as_of=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    ) == ()
