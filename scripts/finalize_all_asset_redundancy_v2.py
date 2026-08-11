from __future__ import annotations

from pathlib import Path


def patch(path: str, old: str, new: str, *, count: int = 1) -> None:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual < count:
        raise SystemExit(
            f"required patch anchor missing in {path}: expected>={count}, got={actual}: {old[:100]!r}"
        )
    source.write_text(text.replace(old, new, count), encoding="utf-8")


# Predeclare all non-option history candidates even when the legacy first pass succeeds.
# This makes configured-but-unattempted fallbacks visible in the CIO cycle audit.
probe = Path("operations/redundant_market_probe.py")
text = probe.read_text(encoding="utf-8")
old = '''    # Preserve current provider-native behavior first; redundancy only repairs missing
    # authentic evidence and cannot override a valid canonical first-pass result.
    result = dict(_legacy.default_market_probe(records, timestamp, policy, http_get=http_get))
    _mark_existing_result_usage(records, result)
    missing = tuple(record for record in records if record.symbol not in result and record.asset_class is not CandidateAssetClass.OPTION)
    if missing:
        eodhd = _legacy.build_eodhd_provider()
        tradier = TradierMarketDataProvider()
        massive = MassiveMultiAssetProvider()
        twelve = TwelveDataHistoryProvider()
        coinbase = CoinbaseHistoryProvider()
        kraken = KrakenHistoryProvider()
        databento_futures = DatabentoFuturesHistoryProvider()
        router = RedundantMarketHistoryRouter()
        for record in missing:
            candidates = _candidate_set(
                record,
                as_of=timestamp,
                policy=policy,
                http_get=http_get,
                eodhd_provider=eodhd,
                tradier=tradier,
                massive=massive,
                twelve=twelve,
                coinbase=coinbase,
                kraken=kraken,
                databento_futures=databento_futures,
            )
'''
new = '''    eodhd = _legacy.build_eodhd_provider()
    tradier = TradierMarketDataProvider()
    massive = MassiveMultiAssetProvider()
    twelve = TwelveDataHistoryProvider()
    coinbase = CoinbaseHistoryProvider()
    kraken = KrakenHistoryProvider()
    databento_futures = DatabentoFuturesHistoryProvider()
    ledger = current_redundancy_ledger()
    candidate_sets: dict[str, tuple[MarketHistoryCandidate, ...]] = {}
    for record in records:
        if record.asset_class is CandidateAssetClass.OPTION:
            continue
        candidates = _candidate_set(
            record,
            as_of=timestamp,
            policy=policy,
            http_get=http_get,
            eodhd_provider=eodhd,
            tradier=tradier,
            massive=massive,
            twelve=twelve,
            coinbase=coinbase,
            kraken=kraken,
            databento_futures=databento_futures,
        )
        candidate_sets[record.symbol] = candidates
        if ledger is not None:
            for candidate in candidates:
                ledger.declare(
                    candidate.key,
                    configured=candidate.configured,
                    authenticated=candidate.authenticated,
                    routed=True,
                    certified_for_evidence_role=candidate.certified_for_evidence_role,
                )

    # Preserve current provider-native behavior first; redundancy only repairs missing
    # authentic evidence and cannot override a valid canonical first-pass result.
    result = dict(_legacy.default_market_probe(records, timestamp, policy, http_get=http_get))
    _mark_existing_result_usage(records, result)
    missing = tuple(
        record
        for record in records
        if record.symbol not in result and record.asset_class is not CandidateAssetClass.OPTION
    )
    if missing:
        router = RedundantMarketHistoryRouter()
        for record in missing:
            candidates = candidate_sets.get(record.symbol, ())
'''
if old not in text:
    raise SystemExit("redundant market predeclaration anchor missing")
text = text.replace(old, new, 1)
probe.write_text(text, encoding="utf-8")

# Directly instrument the Databento/Massive option router so the cycle audit records
# actual attempts and failover, not a post-hoc inference.
options = Path("providers/redundant_options.py")
text = options.read_text(encoding="utf-8")
text = text.replace(
    "from providers.massive_options import (\n",
    "from providers.redundancy_audit import (\n"
    "    ProviderCapabilityKey,\n"
    "    current_redundancy_ledger,\n"
    ")\n"
    "from providers.massive_options import (\n",
    1,
)
helper_anchor = "\n\nclass RedundantOptionsProvider:\n"
helper = '''

def _option_audit_keys(capability: str):
    ledger = current_redundancy_ledger()
    primary_key = ProviderCapabilityKey(
        "databento", capability, DATABENTO_OPRA_DATASET
    )
    fallback_key = ProviderCapabilityKey(
        "massive", capability, MASSIVE_OPRA_DATASET
    )
    return ledger, primary_key, fallback_key


def _selection_sources(selections: Sequence[RedundantOptionSelection]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            source
            for item in selections
            for source in (
                item.definition.source_identifier,
                item.bar.source_identifier,
            )
            if source
        )
    )

'''
if helper_anchor not in text:
    raise SystemExit("options helper anchor missing")
text = text.replace(helper_anchor, helper + helper_anchor, 1)

old_select_start = '''        timestamp = _aware(as_of, field_name="as_of")
        primary_error: BaseException | None = None
        if self.primary.configured:
            try:
'''
new_select_start = '''        timestamp = _aware(as_of, field_name="as_of")
        ledger, primary_key, fallback_key = _option_audit_keys("option_contract_selection")
        if ledger is not None:
            ledger.declare(
                primary_key,
                configured=self.primary.configured,
                authenticated=False,
                routed=True,
                certified_for_evidence_role=True,
            )
            ledger.declare(
                fallback_key,
                configured=self.fallback.configured,
                authenticated=False,
                routed=True,
                certified_for_evidence_role=True,
            )
        primary_error: BaseException | None = None
        if self.primary.configured:
            if ledger is not None:
                ledger.attempted(primary_key)
            try:
'''
if old_select_start not in text:
    raise SystemExit("options select start anchor missing")
text = text.replace(old_select_start, new_select_start, 1)
old_primary_return = '''                if selections:
                    return tuple(_adapt_databento_selection(item) for item in selections)
            except DatabentoOptionsError as error:
                primary_error = error
'''
new_primary_return = '''                if selections:
                    adapted = tuple(_adapt_databento_selection(item) for item in selections)
                    if ledger is not None:
                        ledger.used(
                            primary_key,
                            source_identifiers=_selection_sources(adapted),
                            failed_over=False,
                        )
                    return adapted
                if ledger is not None:
                    ledger.failed(primary_key, "insufficient_evidence")
            except DatabentoOptionsError as error:
                primary_error = error
                if ledger is not None:
                    ledger.failed(primary_key, _failure_class(error))
'''
if old_primary_return not in text:
    raise SystemExit("options primary return anchor missing")
text = text.replace(old_primary_return, new_primary_return, 1)
old_fallback_try = '''        if self.fallback.configured:
            try:
                # Massive Options Basic is request-limited. Preserve the complete
'''
new_fallback_try = '''        if self.fallback.configured:
            if ledger is not None:
                ledger.attempted(fallback_key)
            try:
                # Massive Options Basic is request-limited. Preserve the complete
'''
text = text.replace(old_fallback_try, new_fallback_try, 1)
old_fallback_return = '''                return tuple(_adapt_massive_selection(item) for item in selections)
            except MassiveOptionsError as fallback_error:
                raise RedundantOptionsError(
'''
new_fallback_return = '''                adapted = tuple(_adapt_massive_selection(item) for item in selections)
                if adapted:
                    if ledger is not None:
                        ledger.used(
                            fallback_key,
                            source_identifiers=_selection_sources(adapted),
                            failed_over=bool(self.primary.configured),
                        )
                    return adapted
                if ledger is not None:
                    ledger.failed(fallback_key, "insufficient_evidence")
                return adapted
            except MassiveOptionsError as fallback_error:
                if ledger is not None:
                    ledger.failed(fallback_key, _failure_class(fallback_error))
                raise RedundantOptionsError(
'''
if old_fallback_return not in text:
    raise SystemExit("options fallback return anchor missing")
text = text.replace(old_fallback_return, new_fallback_return, 1)

old_bars_start = '''        timestamp = _aware(as_of, field_name="as_of")
        normalized = tuple(
'''
new_bars_start = '''        timestamp = _aware(as_of, field_name="as_of")
        ledger, primary_key, fallback_key = _option_audit_keys("option_daily_history")
        if ledger is not None:
            ledger.declare(
                primary_key,
                configured=self.primary.configured,
                authenticated=False,
                routed=True,
                certified_for_evidence_role=True,
            )
            ledger.declare(
                fallback_key,
                configured=self.fallback.configured,
                authenticated=False,
                routed=True,
                certified_for_evidence_role=True,
            )
        normalized = tuple(
'''
# This exact anchor occurs only in latest_daily_bars after select was already changed.
if old_bars_start not in text:
    raise SystemExit("options bars start anchor missing")
text = text.replace(old_bars_start, new_bars_start, 1)
old_primary_bars = '''        if self.primary.configured and primary_instruments:
            try:
                _session, primary_bars = self.primary.latest_daily_bars(
'''
new_primary_bars = '''        if self.primary.configured and primary_instruments:
            if ledger is not None:
                ledger.attempted(primary_key)
            try:
                _session, primary_bars = self.primary.latest_daily_bars(
'''
text = text.replace(old_primary_bars, new_primary_bars, 1)
old_primary_bars_end = '''                for raw_symbol, bars in primary_bars.items():
                    result[str(raw_symbol).strip().upper()] = tuple(
                        _adapt_databento_bar(item) for item in bars
                    )
            except DatabentoOptionsError as error:
                primary_error = error
'''
new_primary_bars_end = '''                primary_sources: list[str] = []
                for raw_symbol, bars in primary_bars.items():
                    adapted_bars = tuple(_adapt_databento_bar(item) for item in bars)
                    result[str(raw_symbol).strip().upper()] = adapted_bars
                    primary_sources.extend(item.source_identifier for item in adapted_bars)
                if primary_sources and ledger is not None:
                    ledger.used(
                        primary_key,
                        source_identifiers=tuple(dict.fromkeys(primary_sources)),
                        failed_over=False,
                    )
            except DatabentoOptionsError as error:
                primary_error = error
                if ledger is not None:
                    ledger.failed(primary_key, _failure_class(error))
'''
if old_primary_bars_end not in text:
    raise SystemExit("options primary bars end anchor missing")
text = text.replace(old_primary_bars_end, new_primary_bars_end, 1)
old_fallback_bars = '''        if missing and self.fallback.configured:
            aliases = {_massive_ticker(raw_symbol): raw_symbol for raw_symbol in missing}
            try:
'''
new_fallback_bars = '''        if missing and self.fallback.configured:
            aliases = {_massive_ticker(raw_symbol): raw_symbol for raw_symbol in missing}
            if ledger is not None:
                ledger.attempted(fallback_key)
            try:
'''
text = text.replace(old_fallback_bars, new_fallback_bars, 1)
old_fallback_bars_end = '''                for massive_symbol, bars in fallback_bars.items():
                    normalized_massive = str(massive_symbol).strip().upper()
                    original_symbol = aliases.get(normalized_massive, normalized_massive)
                    result[original_symbol] = tuple(
                        _adapt_massive_bar(item, raw_symbol=original_symbol)
                        for item in bars
                    )
            except MassiveOptionsError as error:
                fallback_error = error
'''
new_fallback_bars_end = '''                fallback_sources: list[str] = []
                for massive_symbol, bars in fallback_bars.items():
                    normalized_massive = str(massive_symbol).strip().upper()
                    original_symbol = aliases.get(normalized_massive, normalized_massive)
                    adapted_bars = tuple(
                        _adapt_massive_bar(item, raw_symbol=original_symbol)
                        for item in bars
                    )
                    result[original_symbol] = adapted_bars
                    fallback_sources.extend(item.source_identifier for item in adapted_bars)
                if fallback_sources and ledger is not None:
                    ledger.used(
                        fallback_key,
                        source_identifiers=tuple(dict.fromkeys(fallback_sources)),
                        failed_over=True,
                    )
            except MassiveOptionsError as error:
                fallback_error = error
                if ledger is not None:
                    ledger.failed(fallback_key, _failure_class(error))
'''
if old_fallback_bars_end not in text:
    raise SystemExit("options fallback bars end anchor missing")
text = text.replace(old_fallback_bars_end, new_fallback_bars_end, 1)
options.write_text(text, encoding="utf-8")

# Add option audit sequence assertions to the existing focused tests.
test = Path("tests/test_redundant_options_provider.py")
text = test.read_text(encoding="utf-8")
text = text.replace(
    "from providers.redundant_options import RedundantOptionsError, RedundantOptionsProvider\n",
    "from providers.redundancy_audit import begin_redundancy_cycle\n"
    "from providers.redundant_options import RedundantOptionsError, RedundantOptionsProvider\n",
    1,
)
text += '''

def test_option_failover_publishes_actual_attempt_sequence() -> None:
    ledger = begin_redundancy_cycle("option-failover", AS_OF)
    provider = RedundantOptionsProvider(
        primary=_CappedPrimary(),
        fallback=_HealthyFallback(),
    )

    selections = _select(provider)

    assert selections[0].definition.provider_kind == "massive"
    records = {
        (item["provider"], item["capability"]): item
        for item in ledger.to_dict()["records"]
    }
    primary = records[("databento", "option_contract_selection")]
    fallback = records[("massive", "option_contract_selection")]
    assert primary["configured"] is True
    assert primary["attempted"] is True
    assert primary["used"] is False
    assert primary["failure_class"] == "access_or_credit_cap"
    assert fallback["configured"] is True
    assert fallback["attempted"] is True
    assert fallback["authenticated"] is True
    assert fallback["used"] is True
    assert fallback["failed_over"] is True


def test_healthy_option_primary_keeps_fallback_visible_but_unattempted() -> None:
    ledger = begin_redundancy_cycle("option-primary", AS_OF)
    provider = RedundantOptionsProvider(
        primary=_HealthyPrimary(),
        fallback=_HealthyFallback(),
    )

    _select(provider)

    records = {
        (item["provider"], item["capability"]): item
        for item in ledger.to_dict()["records"]
    }
    primary = records[("databento", "option_contract_selection")]
    fallback = records[("massive", "option_contract_selection")]
    assert primary["used"] is True
    assert primary["authenticated"] is True
    assert fallback["configured"] is True
    assert fallback["authenticated"] is False
    assert fallback["attempted"] is False
    assert fallback["used"] is False
'''
test.write_text(text, encoding="utf-8")
