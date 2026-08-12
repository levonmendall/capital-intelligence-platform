from __future__ import annotations

from providers.provider_activation_audit import audit_provider_activation


def _record(records, provider_id: str):
    return next(item for item in records if item.provider_id == provider_id)


def test_free_derivative_sources_report_exact_missing_inputs(tmp_path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "all_market_provider_bundle.json").write_text(
        '{"schema_version":"all-market-provider-bundle.v1","members":[]}',
        encoding="utf-8",
    )

    records = audit_provider_activation({}, repository_root=tmp_path)

    cme = _record(records, "cme-margin-data")
    assert cme.state == "missing_credential"
    assert cme.credential_required is True
    assert cme.credential_configured is False
    assert "CAPITAL_INTELLIGENCE_CME_DATAMINE_API_ID" in cme.credential_names
    assert "CAPITAL_INTELLIGENCE_CME_DATAMINE_API_PASSWORD" in cme.credential_names

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
        "CAPITAL_INTELLIGENCE_CME_DATAMINE_API_ID": "cme-id",
        "CAPITAL_INTELLIGENCE_CME_DATAMINE_API_PASSWORD": "cme-password",
        "CAPITAL_INTELLIGENCE_CME_MARGIN_BINDING": "config/cme_span_datamine_file_ids.json",
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

    cme = _record(records, "cme-margin-data")
    assert cme.state == "active"
    assert cme.credential_configured is True
    assert cme.configuration_required is True
    assert cme.configuration_configured is True
    assert cme.production_route is not None

    for provider_id in ("occ-margin-data", "derived-volatility-surfaces"):
        record = _record(records, provider_id)
        assert record.state == "keyless_active"
        assert record.configuration_required is True
        assert record.configuration_configured is True
        assert record.production_route is not None
