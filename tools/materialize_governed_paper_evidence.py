from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(f"expected one match in {path}, found {source.count(old)}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


def patch_alpaca() -> None:
    replace_once(
        "providers/alpaca_paper.py",
        "The adapters expose account, asset, clock, and IEX quote evidence only. They do\nnot submit orders and cannot authorize real-money activity. The canonical paper\nexecutor remains the sole fill and portfolio-state authority.",
        "The adapters expose account, asset, clock, IEX quote, and authenticated IEX\nhistorical-bar evidence only. They do not submit orders and cannot authorize\nreal-money activity. The canonical paper executor remains the sole fill and\nportfolio-state authority.",
    )
    anchor = '''    def latest_quotes(self, symbols: Sequence[str]) -> Mapping[str, Mapping[str, Any]]:\n        normalized = tuple(\n            dict.fromkeys(_text(item, field_name="symbol").upper() for item in symbols)\n        )\n        if not normalized:\n            return {}\n        payload = self._get(\n            self.settings.data_base_url,\n            "/v2/stocks/quotes/latest",\n            params={\n                "symbols": ",".join(normalized),\n                "feed": self.settings.data_feed.lower(),\n            },\n        )\n        quotes = payload.get("quotes")\n        if not isinstance(quotes, Mapping):\n            raise AlpacaPaperProviderError("Alpaca latest-quotes response is missing quotes")\n        result: dict[str, Mapping[str, Any]] = {}\n        for symbol in normalized:\n            quote = quotes.get(symbol)\n            if not isinstance(quote, Mapping):\n                raise AlpacaPaperProviderError(f"Alpaca quote is unavailable for {symbol}")\n            result[symbol] = quote\n        return result\n'''
    addition = anchor + '''\n    def historical_bars(\n        self,\n        symbols: Sequence[str],\n        *,\n        start: datetime,\n        end: datetime,\n        timeframe: str = "1Day",\n        limit: int = 10_000,\n    ) -> Mapping[str, tuple[Mapping[str, Any], ...]]:\n        """Return paginated authenticated IEX bars without order authority."""\n\n        normalized = tuple(\n            dict.fromkeys(_text(item, field_name="symbol").upper() for item in symbols)\n        )\n        if not normalized:\n            return {}\n        for field_name, value in (("start", start), ("end", end)):\n            if value.tzinfo is None or value.utcoffset() is None:\n                raise ValueError(f"{field_name} must be timezone-aware")\n        if start >= end:\n            raise ValueError("historical bar start must predate end")\n        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:\n            raise ValueError("historical bar limit must be between 1 and 10000")\n        result: dict[str, list[Mapping[str, Any]]] = {symbol: [] for symbol in normalized}\n        page_token: str | None = None\n        for _page in range(100):\n            params: dict[str, object] = {\n                "symbols": ",".join(normalized),\n                "timeframe": _text(timeframe, field_name="timeframe"),\n                "start": start.astimezone(timezone.utc).isoformat(),\n                "end": end.astimezone(timezone.utc).isoformat(),\n                "limit": limit,\n                "adjustment": "all",\n                "feed": self.settings.data_feed.lower(),\n                "sort": "asc",\n            }\n            if page_token is not None:\n                params["page_token"] = page_token\n            payload = self._get(\n                self.settings.data_base_url,\n                "/v2/stocks/bars",\n                params=params,\n            )\n            bars = payload.get("bars")\n            if not isinstance(bars, Mapping):\n                raise AlpacaPaperProviderError("Alpaca historical-bars response is missing bars")\n            for symbol in normalized:\n                values = bars.get(symbol, ())\n                if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):\n                    raise AlpacaPaperProviderError(\n                        f"Alpaca historical bars are invalid for {symbol}"\n                    )\n                for item in values:\n                    if not isinstance(item, Mapping):\n                        raise AlpacaPaperProviderError(\n                            f"Alpaca historical bar is invalid for {symbol}"\n                        )\n                    result[symbol].append(item)\n            raw_token = payload.get("next_page_token")\n            if raw_token is None or not str(raw_token).strip():\n                break\n            page_token = str(raw_token).strip()\n        else:\n            raise AlpacaPaperProviderError("Alpaca historical bars exceeded pagination limit")\n        return {symbol: tuple(values) for symbol, values in result.items()}\n'''
    replace_once("providers/alpaca_paper.py", anchor, addition)


def patch_production_context() -> None:
    replace_once(
        "application/production_context.py",
        "from committee.specialists import MacroSpecialistContext, MarketSpecialistContext",
        '''from committee.specialists import (\n    AssetValuationSpecialistContext,\n    CrossAssetForecastSpecialistContext,\n    ForecastScenarioAssessment,\n    MacroSpecialistContext,\n    MarketSpecialistContext,\n)''',
    )
    replace_once(
        "application/production_context.py",
        '''    fundamental_model_version: str\n    lineage: GovernedEvidenceLineage\n''',
        '''    fundamental_model_version: str\n    lineage: GovernedEvidenceLineage\n    forecast: CrossAssetForecastSpecialistContext | None = None\n    asset_valuation: AssetValuationSpecialistContext | None = None\n''',
    )
    replace_once(
        "application/production_context.py",
        '''        if not isinstance(self.lineage, GovernedEvidenceLineage):\n            raise TypeError("lineage must be GovernedEvidenceLineage")\n        self.lineage.require_usable(knowledge_cutoff=self.knowledge_cutoff)\n\n\n@dataclass(frozen=True, slots=True)\nclass ProductionHoldingEvidence:''',
        '''        if not isinstance(self.lineage, GovernedEvidenceLineage):\n            raise TypeError("lineage must be GovernedEvidenceLineage")\n        self.lineage.require_usable(knowledge_cutoff=self.knowledge_cutoff)\n        if self.forecast is not None:\n            if not isinstance(self.forecast, CrossAssetForecastSpecialistContext):\n                raise TypeError(\n                    "forecast must be CrossAssetForecastSpecialistContext or None"\n                )\n            if self.forecast.as_of != self.as_of:\n                raise ValueError("forecast evidence must share candidate as_of")\n        if self.asset_valuation is not None:\n            if not isinstance(self.asset_valuation, AssetValuationSpecialistContext):\n                raise TypeError(\n                    "asset_valuation must be AssetValuationSpecialistContext or None"\n                )\n            if self.asset_valuation.as_of != self.as_of:\n                raise ValueError("asset valuation evidence must share candidate as_of")\n\n\n@dataclass(frozen=True, slots=True)\nclass ProductionHoldingEvidence:''',
    )
    replace_once(
        "application/production_context.py",
        '''            if (\n                candidate.instrument.asset_class is CandidateAssetClass.US_EQUITY\n                and governed.company is None\n            ):\n                raise ProductionContextError(\n                    f"equity candidate {candidate_identifier} is missing governed "\n                    "fundamental and valuation analysis"\n                )\n''',
        '''            if (\n                candidate.instrument.asset_class is CandidateAssetClass.US_EQUITY\n                and governed.company is None\n            ):\n                raise ProductionContextError(\n                    f"equity candidate {candidate_identifier} is missing governed "\n                    "fundamental and valuation analysis"\n                )\n            if governed.company is None and governed.asset_valuation is None:\n                raise ProductionContextError(\n                    f"candidate {candidate_identifier} is missing independent valuation evidence"\n                )\n            if governed.forecast is None:\n                raise ProductionContextError(\n                    f"candidate {candidate_identifier} is missing governed forecast translation"\n                )\n''',
    )
    replace_once(
        "application/production_context.py",
        '''                macro=candidate_evidence[candidate_identifier].macro,\n                market=candidate_evidence[candidate_identifier].market,\n                company=candidate_evidence[candidate_identifier].company,\n''',
        '''                macro=candidate_evidence[candidate_identifier].macro,\n                market=candidate_evidence[candidate_identifier].market,\n                forecast=candidate_evidence[candidate_identifier].forecast,\n                company=candidate_evidence[candidate_identifier].company,\n                asset_valuation=(\n                    candidate_evidence[candidate_identifier].asset_valuation\n                ),\n''',
    )
    helpers = '''\n\ndef _forecast_to_dict(\n    value: CrossAssetForecastSpecialistContext,\n) -> dict[str, Any]:\n    return {\n        "as_of": value.as_of.isoformat(),\n        "forecast_horizon_days": value.forecast_horizon_days,\n        "scenarios": [\n            {\n                "label": item.label,\n                "probability": item.probability,\n                "candidate_return_impact": item.candidate_return_impact,\n                "expected_path_drawdown": item.expected_path_drawdown,\n                "rationale": item.rationale,\n                "evidence_identifiers": list(item.evidence_identifiers),\n            }\n            for item in value.scenarios\n        ],\n        "aggregate_confidence": value.aggregate_confidence,\n        "calibration_score": value.calibration_score,\n        "model_agreement": value.model_agreement,\n        "forecast_stability": value.forecast_stability,\n        "path_drawdown_probability": value.path_drawdown_probability,\n        "cross_asset_signals": list(value.cross_asset_signals),\n        "contradictory_evidence": list(value.contradictory_evidence),\n        "limitations": list(value.limitations),\n        "change_conditions": list(value.change_conditions),\n        "model_versions": list(value.model_versions),\n        "evidence_identifiers": list(value.evidence_identifiers),\n        "evidence_dependencies": [\n            {\n                "identifier": item.identifier,\n                "parent_identifiers": list(item.parent_identifiers),\n            }\n            for item in value.evidence_dependencies\n        ],\n    }\n\n\ndef _forecast_from_dict(\n    payload: Mapping[str, Any],\n) -> CrossAssetForecastSpecialistContext:\n    from cio import EvidenceDependency\n\n    return CrossAssetForecastSpecialistContext(\n        as_of=datetime.fromisoformat(str(payload["as_of"])),\n        forecast_horizon_days=int(payload["forecast_horizon_days"]),\n        scenarios=tuple(\n            ForecastScenarioAssessment(\n                label=str(item["label"]),\n                probability=float(item["probability"]),\n                candidate_return_impact=float(item["candidate_return_impact"]),\n                expected_path_drawdown=float(item["expected_path_drawdown"]),\n                rationale=str(item["rationale"]),\n                evidence_identifiers=tuple(\n                    str(value) for value in item["evidence_identifiers"]\n                ),\n            )\n            for item in payload["scenarios"]\n        ),\n        aggregate_confidence=float(payload["aggregate_confidence"]),\n        calibration_score=float(payload["calibration_score"]),\n        model_agreement=float(payload["model_agreement"]),\n        forecast_stability=float(payload["forecast_stability"]),\n        path_drawdown_probability=float(payload["path_drawdown_probability"]),\n        cross_asset_signals=tuple(\n            str(item) for item in payload["cross_asset_signals"]\n        ),\n        contradictory_evidence=tuple(\n            str(item) for item in payload.get("contradictory_evidence", ())\n        ),\n        limitations=tuple(str(item) for item in payload["limitations"]),\n        change_conditions=tuple(\n            str(item) for item in payload["change_conditions"]\n        ),\n        model_versions=tuple(str(item) for item in payload["model_versions"]),\n        evidence_identifiers=tuple(\n            str(item) for item in payload["evidence_identifiers"]\n        ),\n        evidence_dependencies=tuple(\n            EvidenceDependency(\n                identifier=str(item["identifier"]),\n                parent_identifiers=tuple(\n                    str(value) for value in item["parent_identifiers"]\n                ),\n            )\n            for item in payload.get("evidence_dependencies", ())\n        ),\n    )\n\n\ndef _asset_valuation_to_dict(\n    value: AssetValuationSpecialistContext,\n) -> dict[str, Any]:\n    return {\n        "as_of": value.as_of.isoformat(),\n        "asset_class": value.asset_class.value,\n        "expected_return_impact": value.expected_return_impact,\n        "confidence": value.confidence,\n        "valuation_evidence": list(value.valuation_evidence),\n        "contradictory_evidence": list(value.contradictory_evidence),\n        "critical_assumptions": list(value.critical_assumptions),\n        "risks": list(value.risks),\n        "limitations": list(value.limitations),\n        "change_conditions": list(value.change_conditions),\n        "evidence_identifiers": list(value.evidence_identifiers),\n    }\n\n\ndef _asset_valuation_from_dict(\n    payload: Mapping[str, Any],\n) -> AssetValuationSpecialistContext:\n    return AssetValuationSpecialistContext(\n        as_of=datetime.fromisoformat(str(payload["as_of"])),\n        asset_class=CandidateAssetClass(str(payload["asset_class"])),\n        expected_return_impact=float(payload["expected_return_impact"]),\n        confidence=float(payload["confidence"]),\n        valuation_evidence=tuple(\n            str(item) for item in payload["valuation_evidence"]\n        ),\n        contradictory_evidence=tuple(\n            str(item) for item in payload.get("contradictory_evidence", ())\n        ),\n        critical_assumptions=tuple(\n            str(item) for item in payload["critical_assumptions"]\n        ),\n        risks=tuple(str(item) for item in payload["risks"]),\n        limitations=tuple(str(item) for item in payload["limitations"]),\n        change_conditions=tuple(\n            str(item) for item in payload["change_conditions"]\n        ),\n        evidence_identifiers=tuple(\n            str(item) for item in payload["evidence_identifiers"]\n        ),\n    )\n'''
    replace_once(
        "application/production_context.py",
        "\ndef _quality_to_dict(value: EvidenceQuality) -> dict[str, float]:",
        helpers + "\n\ndef _quality_to_dict(value: EvidenceQuality) -> dict[str, float]:",
    )
    replace_once(
        "application/production_context.py",
        '''        "company": (\n            None if value.company is None else _company_to_dict(value.company)\n        ),\n        "exposure_profile": _profile_to_dict(value.exposure_profile),\n''',
        '''        "company": (\n            None if value.company is None else _company_to_dict(value.company)\n        ),\n        "forecast": (\n            None if value.forecast is None else _forecast_to_dict(value.forecast)\n        ),\n        "asset_valuation": (\n            None\n            if value.asset_valuation is None\n            else _asset_valuation_to_dict(value.asset_valuation)\n        ),\n        "exposure_profile": _profile_to_dict(value.exposure_profile),\n''',
    )
    replace_once(
        "application/production_context.py",
        '''    company_payload = payload.get("company")\n    return ProductionCandidateEvidence(\n''',
        '''    company_payload = payload.get("company")\n    forecast_payload = payload.get("forecast")\n    asset_valuation_payload = payload.get("asset_valuation")\n    return ProductionCandidateEvidence(\n''',
    )
    replace_once(
        "application/production_context.py",
        '''        lineage=_lineage_from_dict(dict(payload["lineage"])),\n    )\n''',
        '''        lineage=_lineage_from_dict(dict(payload["lineage"])),\n        forecast=(\n            None\n            if forecast_payload is None\n            else _forecast_from_dict(dict(forecast_payload))\n        ),\n        asset_valuation=(\n            None\n            if asset_valuation_payload is None\n            else _asset_valuation_from_dict(dict(asset_valuation_payload))\n        ),\n    )\n''',
    )
    replace_once(
        "application/production_context_adapter.py",
        '''                asset_valuation=(\n                    None\n                    if context.candidate_identifier not in packet_by_candidate\n                    else _asset_valuation_context(\n                        packet_by_candidate[context.candidate_identifier]\n                    )\n                ),\n''',
        '''                asset_valuation=(\n                    context.asset_valuation\n                    if context.candidate_identifier not in packet_by_candidate\n                    else _asset_valuation_context(\n                        packet_by_candidate[context.candidate_identifier]\n                    )\n                ),\n''',
    )


def patch_runtime_delegate() -> None:
    replace_once(
        "production_context_publication_runtime.py",
        "def prepare_production_context_for_cycle(\n",
        "def _prepare_exclusion_only_production_context_for_cycle(\n",
    )
    wrapper = '''\n\ndef prepare_production_context_for_cycle(\n    *,\n    settings: ApiSettings,\n    scheduled_for: datetime,\n    universe_path: str | Path = DEFAULT_UNIVERSE_PATH,\n    readiness_probe: ReadinessProbe | None = None,\n    cash_probe: CashProbe | None = None,\n    evidence_probe=None,\n    clock: Clock | None = None,\n) -> ProductionContextPublicationResult:\n    """Publish decision-complete candidate and holding evidence for the paper cycle."""\n\n    from production_context_publication_governed import (\n        prepare_governed_production_context_for_cycle,\n    )\n\n    return prepare_governed_production_context_for_cycle(\n        settings=settings,\n        scheduled_for=scheduled_for,\n        universe_path=universe_path,\n        readiness_probe=readiness_probe,\n        cash_probe=cash_probe,\n        evidence_probe=evidence_probe,\n        clock=clock,\n    )\n'''
    replace_once(
        "production_context_publication_runtime.py",
        '\n\n__all__ = [\n    "ProductionContextPublicationResult",',
        wrapper + '\n\n__all__ = [\n    "ProductionContextPublicationResult",',
    )


def cleanup_inventory() -> None:
    for relative in (
        "reports/paper-evidence-component-inventory.json",
        "reports/paper-evidence-path-summary.md",
    ):
        path = ROOT / relative
        if path.exists():
            path.unlink()


def main() -> None:
    patch_alpaca()
    patch_production_context()
    patch_runtime_delegate()
    cleanup_inventory()


if __name__ == "__main__":
    main()
