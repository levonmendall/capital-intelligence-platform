from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from data.decision_information import DecisionInformationRecord,InformationProvenance,InformationQualityState,InformationSourceType,PortfolioImpactChannel
from intelligence.event_market import EventCoverageState,EventMarketDomain,EventMarketState,EventToMarketEngine,GovernedEventMarketService,MarketObservation,SQLiteEventMarketStore,TransmissionDirection
AS_OF=datetime(2026,8,2,23,0,tzinfo=timezone.utc)

def record(identifier,topic,summary,channels,tags=(),entities=('Entity',),sectors=('Sector',),materiality=.9):
    return DecisionInformationRecord(identifier,topic,summary,AS_OF,AS_OF,AS_OF,AS_OF,InformationProvenance('Official',f'source:{identifier}',InformationSourceType.OFFICIAL,AS_OF,'license','internal',f'hash:{identifier}',InformationQualityState.LIVE),f'canonical:{identifier}',entities,(),('Global',),sectors,tags,channels,.95,.95,materiality,1.0,(f'wire:{identifier}',))
def cluster(identifier='cluster:x',eligible=True): return SimpleNamespace(identifier=identifier,quality_score=.9,eligible_for_cio_context=eligible,source_identifiers=('official','wire'))
def obs(target,move): return MarketObservation(f'obs:{target}',target,AS_OF,move,(f'quote:{target}',))

def test_iran_energy_deescalation_keeps_specific_oil_chain():
    r=record('iran','Ceasefire halts strikes near Hormuz','Peace agreement restores oil shipping', (PortfolioImpactChannel.GEOPOLITICAL,PortfolioImpactChannel.SUPPLY,PortfolioImpactChannel.COMMODITY),('ceasefire','oil','hormuz'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster(),observations=(obs('crude_oil',-.05),obs('broad_equities',.02),obs('airlines',.02),obs('volatility',-.04)),assessed_at=AS_OF)
    assert a.state is EventMarketState.GEOPOLITICAL_DEESCALATION
    assert a.transmission('crude_oil').direction is TransmissionDirection.NEGATIVE
    assert a.transmission('airlines').direction is TransmissionDirection.POSITIVE
    assert a.eligible_for_cio_context
    assert EventMarketDomain.COMMODITY_SUPPLY in a.domains

def test_hot_cpi_maps_rates_bonds_growth_equities_and_dollar():
    r=record('cpi','CPI beats forecasts as core inflation accelerates','Hot inflation raises rate expectations',(PortfolioImpactChannel.INFLATION,PortfolioImpactChannel.POLICY,PortfolioImpactChannel.DISCOUNT_RATE),('cpi beats','hot inflation'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:cpi'),observations=(obs('inflation_expectations',.02),obs('bond_prices',-.015),obs('growth_equities',-.02),obs('us_dollar',.01)),assessed_at=AS_OF)
    assert a.state is EventMarketState.INFLATION_ACCELERATION
    assert a.transmission('bond_prices').direction is TransmissionDirection.NEGATIVE
    assert a.transmission('growth_equities').direction is TransmissionDirection.NEGATIVE
    assert a.transmission('us_dollar').direction is TransmissionDirection.POSITIVE
    assert a.eligible_for_cio_context

def test_dovish_cut_and_weak_growth_combine_instead_of_one_story_rule():
    r=record('fed-recession','Federal Reserve cuts rates as recession risk rises','A dovish rate cut follows weakening growth and layoffs',(PortfolioImpactChannel.POLICY,PortfolioImpactChannel.GROWTH,PortfolioImpactChannel.CREDIT),('rate cut','recession','layoffs'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:fed'),observations=(obs('bond_prices',.02),obs('credit',-.01),obs('cyclical_equities',-.015)),assessed_at=AS_OF)
    assert EventMarketDomain.MONETARY_POLICY in a.domains
    assert EventMarketDomain.MACRO_GROWTH in a.domains
    assert len(a.drivers)>=2
    assert a.transmission('bond_prices').direction is TransmissionDirection.POSITIVE
    assert a.transmission('credit').direction is TransmissionDirection.MIXED
    assert a.coverage_state is EventCoverageState.PARTIAL

def test_earnings_beat_is_issuer_specific_and_maps_candidate():
    r=record('earnings','Company earnings beat and guidance raised','Revenue beat and margins expand',(PortfolioImpactChannel.EARNINGS,PortfolioImpactChannel.SENTIMENT),('earnings beat','guidance raised'),entities=('Issuer A',),sectors=('Semiconductors',))
    engine=EventToMarketEngine(); a=engine.assess(r,event_cluster=cluster('cluster:earnings'),observations=(obs('affected_issuer',.08),obs('affected_sector',.02)),assessed_at=AS_OF)
    e=engine.candidate_evidence(a,candidate_exposure_map={'affected_issuer':('candidate:A',),'affected_sector':('candidate:SOXX',)})
    assert a.state is EventMarketState.CORPORATE_POSITIVE
    assert a.transmission('affected_issuer').direction is TransmissionDirection.POSITIVE
    assert {x.candidate_identifier for x in e}=={'candidate:A','candidate:SOXX'}

def test_bank_failure_maps_credit_financials_volatility_and_safe_haven():
    r=record('bank','Regional bank fails after deposit outflows','A bank run and liquidity crisis trigger rescue talks',(PortfolioImpactChannel.CREDIT,PortfolioImpactChannel.LIQUIDITY,PortfolioImpactChannel.COUNTERPARTY,PortfolioImpactChannel.VOLATILITY),('bank failure','deposit outflow'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:bank'),observations=(obs('credit',-.02),obs('financials',-.04),obs('volatility',.08),obs('treasuries',.015)),assessed_at=AS_OF)
    assert a.state is EventMarketState.CREDIT_STRESS
    assert a.transmission('financials').direction is TransmissionDirection.NEGATIVE
    assert a.transmission('treasuries').direction is TransmissionDirection.POSITIVE
    assert a.eligible_for_cio_context

def test_tariffs_map_importers_exporters_inflation_and_supply_chain():
    r=record('tariff','Government imposes new tariffs and export controls','Trade restrictions raise costs for importers and exporters',(PortfolioImpactChannel.REGULATION,PortfolioImpactChannel.SUPPLY,PortfolioImpactChannel.GEOPOLITICAL),('tariff','export control'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:tariff'),observations=(obs('affected_importers',-.02),obs('affected_exporters',-.025),obs('inflation_expectations',.01),obs('supply_chain',-.015)),assessed_at=AS_OF)
    assert a.state is EventMarketState.TRADE_RESTRICTION
    assert a.transmission('domestic_substitutes').direction is TransmissionDirection.POSITIVE
    assert a.eligible_for_cio_context

def test_cyberattack_maps_issuer_customers_and_security_vendors():
    r=record('cyber','Major ransomware cyberattack shuts payment network','Systems outage disrupts customers and operations',(PortfolioImpactChannel.CYBER,PortfolioImpactChannel.OPERATIONAL,PortfolioImpactChannel.EARNINGS),('cyberattack','systems outage'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:cyber'),observations=(obs('affected_issuer',-.06),obs('affected_customers',-.01),obs('cybersecurity_vendors',.02)),assessed_at=AS_OF)
    assert a.state is EventMarketState.OPERATIONAL_DISRUPTION
    assert a.transmission('cybersecurity_vendors').direction is TransmissionDirection.POSITIVE
    assert a.eligible_for_cio_context

def test_hurricane_maps_region_insurers_reconstruction_and_commodity():
    r=record('storm','Major hurricane closes ports and refineries','Disaster declaration follows severe flooding',(PortfolioImpactChannel.CLIMATE_WEATHER,PortfolioImpactChannel.SUPPLY,PortfolioImpactChannel.OPERATIONAL,PortfolioImpactChannel.COMMODITY),('hurricane','port closure','refinery outage'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:storm'),observations=(obs('affected_region',-.03),obs('insurers',-.02),obs('affected_commodity',.03),obs('supply_chain',-.02)),assessed_at=AS_OF)
    assert EventMarketDomain.WEATHER_DISASTER in a.domains
    assert EventMarketDomain.COMMODITY_SUPPLY in a.domains
    assert a.transmission('insurers').direction is TransmissionDirection.NEGATIVE
    assert a.eligible_for_cio_context

def test_novel_major_headline_is_not_ignored_or_given_invented_direction():
    r=record('novel','Major orbital infrastructure incident changes satellite access','An unprecedented event has material market implications but an unclear mechanism',(PortfolioImpactChannel.OPERATIONAL,PortfolioImpactChannel.REGULATION),('unprecedented',),materiality=.95)
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:novel'),observations=(),assessed_at=AS_OF)
    assert a.state is EventMarketState.UNRESOLVED_MAJOR_EVENT
    assert a.coverage_state is EventCoverageState.UNRESOLVED
    assert a.major_headline
    assert a.requires_causal_review
    assert not a.eligible_for_cio_context
    assert all(x.direction is TransmissionDirection.NEUTRAL for x in a.transmissions)
    assert a.unresolved_questions

def test_demand_driven_oil_decline_is_not_equity_bullish():
    r=record('oil-demand','Oil falls as recession and weak demand reduce consumption','Economic slowdown lowers petroleum demand',(PortfolioImpactChannel.GROWTH,PortfolioImpactChannel.DEMAND,PortfolioImpactChannel.COMMODITY),('oil','recession','weak demand'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:oil-demand'),observations=(obs('crude_oil',-.04),obs('broad_equities',-.02),obs('credit',-.01)),assessed_at=AS_OF)
    assert a.state is EventMarketState.DEMAND_WEAKENING
    assert a.transmission('crude_oil').direction is TransmissionDirection.NEGATIVE
    assert a.transmission('broad_equities').direction is TransmissionDirection.NEGATIVE

def test_opposite_market_moves_block_cio_context_and_request_review():
    r=record('contrary','CPI beats forecasts as inflation accelerates','Hot inflation should raise yields',(PortfolioImpactChannel.INFLATION,PortfolioImpactChannel.POLICY),('cpi beats','inflation accelerates'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:contrary'),observations=(obs('bond_prices',.02),obs('growth_equities',.02),obs('inflation_expectations',-.01)),assessed_at=AS_OF)
    assert not a.eligible_for_cio_context
    assert a.requires_causal_review
    assert a.contradictory_evidence

def test_governed_service_requires_both_event_and_portfolio_gates():
    r=record('service','Company earnings beat and guidance raised','Revenue beat and margins expand',(PortfolioImpactChannel.EARNINGS,),('earnings beat','guidance raised'))
    result=GovernedEventMarketService().assess(r,event_cluster=cluster('cluster:service'),observations=(obs('affected_issuer',.06),),portfolio_identifier='COMPOUNDING',owned_instrument_identifiers=('instrument:A',),portfolio_exposure_map={'affected_issuer':('instrument:A',)},candidate_exposure_map={'affected_issuer':('candidate:A',)},assessed_at=AS_OF)
    assert result.requires_cio_review
    assert result.assessment.affected_portfolio_instruments==('instrument:A',)

def test_store_is_idempotent_append_only_and_persists_v2_fields(tmp_path):
    r=record('store','Regional bank fails after deposit outflows','A bank run triggers liquidity stress',(PortfolioImpactChannel.CREDIT,PortfolioImpactChannel.LIQUIDITY),('bank failure','deposit outflow'))
    a=EventToMarketEngine().assess(r,event_cluster=cluster('cluster:store'),observations=(obs('credit',-.02),obs('financials',-.03)),assessed_at=AS_OF)
    store=SQLiteEventMarketStore(tmp_path/'event-market.db'); store.append(a,recorded_at=AS_OF); store.append(a,recorded_at=AS_OF)
    with sqlite3.connect(store.path) as c:
        assert c.execute('select count(*) from event_market_assessments').fetchone()[0]==1
        payload=json.loads(c.execute('select payload_json from event_market_assessments').fetchone()[0])
        with pytest.raises(sqlite3.IntegrityError): c.execute("update event_market_assessments set recorded_at='x'")
        with pytest.raises(sqlite3.IntegrityError): c.execute('delete from event_market_assessments')
    assert payload['schema_version']=='event-market-assessment.v2'
    assert payload['domains']
    assert payload['authorizes_portfolio_change'] is False
