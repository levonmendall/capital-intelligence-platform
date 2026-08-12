from __future__ import annotations

from datetime import datetime, timezone

from operations.provider_validation import ProviderValidationCheck, ProviderValidationReport
from providers.redundant_options import RedundantOptionsError
from run_provider_validation import certify_redundant_option_provider


NOW = datetime(2026, 8, 12, 0, 30, tzinfo=timezone.utc)


def _passed_check(name: str, provider: str) -> ProviderValidationCheck:
    return ProviderValidationCheck(
        name=name,
        provider=provider,
        required=True,
        state="passed",
        detail="passed",
        observed_at=NOW,
        source_identifier=f"{provider.lower()}:{name}",
        evidence_fingerprint="a" * 64,
    )


class _BlockedRouter:
    configured = True

    def select_contracts(self, *_args, **_kwargs):
        raise RedundantOptionsError(
            "Certified option providers cannot supply opportunity-complete evidence; "
            "primary=authentication_or_entitlement; fallback=provider_evidence_unavailable; "
            "primary_detail=Alpaca indicative options returned HTTP 403"
        )


class _Yahoo:
    status_code = 200

    def json(self):
        return {
            "chart": {
                "result": [
                    {"indicators": {"quote": [{"close": [650.0]}]}}
                ]
            }
        }


def test_governed_option_failure_is_published_credential_safely() -> None:
    report = ProviderValidationReport(
        release="release-test",
        generated_at=NOW,
        checks=(
            _passed_check("eodhd_account_entitlement", "EODHD"),
            _passed_check("yahoo_chart_evidence", "YAHOO"),
        ),
    )

    updated = certify_redundant_option_provider(
        report,
        options_provider=_BlockedRouter(),
        http_get=lambda *_args, **_kwargs: _Yahoo(),
    )

    by_name = {item.name: item for item in updated.checks}
    governed = by_name["governed_opra_definitions"]
    assert governed.required is True
    assert governed.state == "failed"
    assert governed.provider == "REDUNDANT_OPTIONS"
    assert "opportunity-complete evidence" in governed.detail
    assert "Alpaca indicative options returned HTTP 403" in governed.detail
    assert governed.source_identifier is None
    assert governed.evidence_fingerprint is None
