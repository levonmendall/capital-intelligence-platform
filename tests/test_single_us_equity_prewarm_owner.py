from __future__ import annotations

import requests

from operations import evidence_preparation_progress as progress


def test_provider_progress_installation_does_not_start_structural_prewarm(monkeypatch):
    started: list[dict[str, str]] = []

    def original_request(_session, *args, **kwargs):
        del args, kwargs
        return object()

    monkeypatch.setattr(requests.sessions.Session, "request", original_request)
    monkeypatch.setattr(
        progress,
        "_start_us_equity_structural_prewarm",
        lambda values: started.append(dict(values)),
    )

    progress.install_post_public_provider_progress(
        values={
            "RENDER": "true",
            "CAPITAL_INTELLIGENCE_EVIDENCE_STAGE": "us_equity_discovery",
        }
    )

    assert started == []
    assert getattr(
        requests.sessions.Session.request,
        "_post_public_provider_progress",
        False,
    ) is True
