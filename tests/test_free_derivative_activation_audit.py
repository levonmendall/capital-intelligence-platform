from __future__ import annotations

from providers.provider_activation_audit import audit_provider_activation


def _record(records, provider_id: str):
    return next(item for item in records if item.provider_id == provider_id)


def test_free_derivative_sources_are_missing_configuration_until_governed_inputs_exist(tmp_path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "all_market_provider_bundle.json").write_text(
        '{"schema_version":"all-market-provider-bundle.v1","members":[]}',
        encoding="utf-8",
    )

    records = audit_provider_activation({}, repository_root=tmp_path)

    assert _record(records, "cme-margin-data").state == "missing_configuration"
    assert _record(records, "occ-margin-data").state == "missing_configuration"
    assert _record(records, "derived-volatility-surfaces").state == "missing_configuration"


def test_free_derivative_sources_become_routed_only_after_all_governed_inputs_exist(tmp_path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "all_market_provider_bundle.json").write_text(
        '{"schema_version":"all-market-provider-bundle.v1","members":[]}',
        encoding="utf-8",
    )
    environment = {
        "CAPITAL_INTELLIGENCE_CME_MARGIN_BINDING": "/data/cme.span",
        "CAPITAL_INTELLIGENCE_CME_MARGIN_TERMS_REFERENCE": "cme-datamine-terms",
        "CAPITAL_INTELLIGENCE_CME_MARGIN_PAPER_USE_APPROVAL": "approved",
        "CAPITAL_INTELLIGENCE_CME_MARGIN_CERTIFICATION_ID": "cert:cme",
        "CAPITAL_INTELLIGENCE_OCC_MARGIN_BINDING": "https://www.theocc.com/ofra/file",
        "CAPITAL_INTELLIGENCE_OCC_MARGIN_TERMS_REFERENCE": "occ-terms",
        "CAPITAL_INTELLIGENCE_OCC_MARGIN_PAPER_USE_APPROVAL": "approved",
        "CAPITAL_INTELLIGENCE_OCC_MARGIN_CERTIFICATION_ID": "cert:occ",
        "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_BINDING": "canonical-option-quotes",
        "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_MODEL_APPROVAL": "approved",
        "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_CERTIFICATION_ID": "cert:surface",
    }

    records = audit_provider_activation(environment, repository_root=tmp_path)

    for provider_id in (
        "cme-margin-data",
        "occ-margin-data",
        "derived-volatility-surfaces",
    ):
        record = _record(records, provider_id)
        assert record.state == "keyless_active"
        assert record.configuration_required is True
        assert record.configuration_configured is True
        assert record.production_route is not None
