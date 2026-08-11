from __future__ import annotations

from datetime import datetime, timezone

from cio_decision_export import build_cio_decision_export
from providers.finra_context import collect_finra_fixed_income_context
from providers.provider_activation_audit import CORE_PROVIDER_ACTIVATION_SPECS
from providers.redundancy_audit import ProviderCapabilityKey, begin_redundancy_cycle
from providers.redundant_market_history import ALL_ASSET_REDUNDANCY_POLICY


# Integration contracts below guard the exact governance boundaries required by PR #576.
AS_OF = datetime(2026, 8, 11, 22, 0, tzinfo=timezone.utc)


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FinraProvider:
    def _access_token(self):
        return "token", "Bearer", 3600


def test_cio_export_publishes_seven_stage_redundancy_audit() -> None:
    ledger = begin_redundancy_cycle("integration-cycle", AS_OF)
    key = ProviderCapabilityKey("massive", "fx_history", "forex-aggs")
    ledger.declare(
        key,
        configured=True,
        authenticated=False,
        routed=True,
        certified_for_evidence_role=True,
    )
    ledger.attempted(key)
    ledger.used(
        key,
        source_identifiers=("market-history:massive:fx_history:forex-aggs:EURUSD",),
        failed_over=True,
    )

    payload = build_cio_decision_export(
        cio_decision=None,
        daily_cio_briefing=None,
        decision_evidence_snapshot=None,
        portfolio_construction=None,
        decision_evaluation=None,
        generated_at=AS_OF,
        release_identifier="test-release",
    )

    audit = payload["provider_redundancy_audit"]
    assert audit["cycle_identifier"] == "integration-cycle"
    record = audit["records"][0]
    assert record["configured"] is True
    assert record["authenticated"] is True
    assert record["routed"] is True
    assert record["certified_for_evidence_role"] is True
    assert record["attempted"] is True
    assert record["used"] is True
    assert record["failed_over"] is True
    assert audit["secret_values_included"] is False
    assert audit["decision_authority_granted"] is False
    assert audit["execution_authority_granted"] is False


def test_fixed_income_price_history_never_uses_finra_or_treasury_reference() -> None:
    fixed_income = ALL_ASSET_REDUNDANCY_POLICY["fixed_income"]

    assert fixed_income["market_context"] == (
        "finra",
        "treasury_fiscal_data",
        "fred",
    )
    assert "finra" not in fixed_income["history"]
    assert "treasury_fiscal_data" not in fixed_income["history"]
    assert fixed_income["history"] == ("ice_evaluated_fixed_income", "eodhd")


def test_activation_registry_keeps_finra_context_and_treasury_reference_roles_separate() -> None:
    specs = {item.provider_id: item for item in CORE_PROVIDER_ACTIVATION_SPECS}

    finra = specs["finra"]
    assert "specialist_environment_context" in finra.evidence_roles
    assert "price" not in " ".join(finra.evidence_roles).lower()
    assert finra.production_route is not None
    assert "context" in finra.production_route.lower()

    treasury = specs["treasury-fiscal-data"]
    assert treasury.evidence_roles == ("treasury_security_reference",)
    assert "price" not in " ".join(treasury.evidence_roles).lower()


def test_finra_context_has_no_instrument_or_individual_price_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        "providers.finra_context.build_finra_fixed_income_provider",
        lambda: _FinraProvider(),
    )
    payload = [
        {
            "tradeDate": "2026-08-10",
            "productCategory": "Treasury",
            "yearsToMaturity": "2-5",
            "dealerCustomerVolume": "100.0",
            "dealerCustomerCount": "10",
            "atsInterdealerVolume": "80.0",
            "atsInterdealerCount": "8",
        }
    ]
    record = collect_finra_fixed_income_context(
        as_of=AS_OF,
        http_get=lambda *args, **kwargs: _Response(payload),
    )

    assert record is not None
    assert record.instruments == ()
    assert "not an individual Treasury or bond price" in record.summary
    assert "aggregate-context-only" in record.tags
    assert any(
        "not individual-security pricing" in item.lower()
        for item in record.provenance.limitations
    )
