# Paper Evidence Path Summary

## `api/app.py`
- Terms: Valuation
- Classes: none
- Functions: create_app

## `api/routes/__init__.py`
- Terms: Valuation
- Classes: none
- Functions: none

## `api/routes/cio.py`
- Terms: Valuation
- Classes: none
- Functions: latest, history, pending_transactions_latest, pending_transactions_history, latest_evaluation, latest_decision, latest_construction, latest_evidence_snapshot, theses, process

## `api/routes/valuation.py`
- Terms: Valuation
- Classes: none
- Functions: _store, latest, history

## `app.py`
- Terms: Valuation
- Classes: none
- Functions: _render_navigation_with_admin_control, _compatible_metric_grid, _compatible_signal_panel, _safe_render_sidebar, _safe_render_app_header, _safe_allocation_bar

## `app_impl.py`
- Terms: Valuation
- Classes: none
- Functions: runtime_settings, cio_journal, diagnostic_snapshots, _latest, _history, _latest_theses, _diagnostic_environment, _render_today, _render_environment, _render_portfolio, _render_history

## `application/__init__.py`
- Terms: ProductionCandidateEvidence, ProductionHoldingEvidence, AssetSpecificEvidencePacket, CandidateForecastSupport
- Classes: none
- Functions: none

## `application/cio_cycle.py`
- Terms: CandidateDecisionRecord, Valuation, LivingThesis, HistoricalLearning
- Classes: CandidateExposureProfile, CyclePortfolioState, CandidateCycleContext, CanonicalCIOCycleResult, CanonicalCIOCycle
- Functions: _required_text, _aware, _loading_tuple, _raise_missing_profile

## `application/daily_intelligence.py`
- Terms: package inventory
- Classes: DailyIntelligenceStatus, DailySnapshotRecord, DailyCapitalIntelligenceSnapshot, DailyIntelligenceCycle, SQLiteDailySnapshotStore, DailyCapitalIntelligenceService
- Functions: build_daily_capital_intelligence_snapshot, daily_snapshot_to_dict, _status_for, _change_summary

## `application/environment_evidence.py`
- Terms: package inventory
- Classes: EnvironmentEvidenceError, EnvironmentEvidenceIntegrityError, CertifiedDecisionEnvironmentSnapshot, SubsequentEnvironmentObservation, SQLiteEnvironmentEvidenceStore
- Functions: _text, _aware, _texts, _pairs, _object, _canonical_json

## `application/forecast_support.py`
- Terms: CandidateForecastSupport
- Classes: ForecastSupportError, ForecastSupportIntegrityError, CandidateForecastScenarioImpact, CandidateForecastSupport, SQLiteCandidateForecastSupportStore, ForecastSupportingProductionContextProvider
- Functions: _texts, _number, _ratio, _canonical_json, _merge_versions, build_production_context_provider

## `application/multi_asset_evidence.py`
- Terms: AssetSpecificEvidencePacket, Valuation
- Classes: MultiAssetEvidenceError, MultiAssetEvidenceIntegrityError, OriginatingFactObservation, MetricDirection, AssetMetricDefinition, TypedAssetMetric, AssetSpecificEvidencePacket, SQLiteAssetSpecificEvidenceStore
- Functions: _text, _texts, _aware, _number, _metrics, _versions, _canonical_json, metric_definition

## `application/production_cio.py`
- Terms: package inventory
- Classes: ProductionContextManifest, ProductionCanonicalCIOContext, ProductionCanonicalCIOContextProvider, ProductionCanonicalCIOExecutor
- Functions: _required_text, _aware, _texts, _versions

## `application/production_context.py`
- Terms: ProductionCandidateEvidence, ProductionHoldingEvidence, Valuation
- Classes: ProductionContextError, EvidenceCertificationState, GovernedEvidenceLineage, ProductionCandidateEvidence, ProductionHoldingEvidence, ProductionContextEvidenceSnapshot, SQLiteProductionContextStore, RepositoryProductionCanonicalCIOContextProvider
- Functions: _text, _aware, _number, _texts, _pairs, _canonical_json, build_production_context_provider, _lineage_to_dict, _lineage_from_dict, _macro_to_dict, _macro_from_dict, _market_to_dict, _market_from_dict, _quality_to_dict, _quality_from_dict, _annual_to_dict, _annual_from_dict, _optional_float, _company_to_dict, _company_from_dict, _profile_to_dict, _profile_from_dict, _candidate_to_dict, _candidate_from_dict, _holding_to_dict, _holding_from_dict, _snapshot_to_dict, _snapshot_from_dict

## `application/production_context_adapter.py`
- Terms: Valuation
- Classes: RepositoryProductionCanonicalCIOContextProvider
- Functions: _merge_versions, _asset_valuation_context, build_production_context_provider

## `application/production_context_contract.py`
- Terms: package inventory
- Classes: ProductionCanonicalCIOContext, ProductionCanonicalCIOExecutor
- Functions: _required_text, _aware

## `application/production_context_runtime.py`
- Terms: Valuation
- Classes: RepositoryProductionCanonicalCIOContextProvider
- Functions: build_production_context_provider

## `cio/__init__.py`
- Terms: CandidateDecisionRecord, HistoricalLearning
- Classes: none
- Functions: __getattr__

## `cio/committee.py`
- Terms: CandidateDecisionRecord, Valuation, HistoricalLearning
- Classes: SpecialistAnalysis, IndependentSpecialistPacket
- Functions: _required_text, _text_tuple

## `cio/governed_historical_learning.py`
- Terms: CandidateDecisionRecord, HistoricalLearning
- Classes: HistoricalLearningResolver
- Functions: none

## `cio/historical_learning.py`
- Terms: CandidateDecisionRecord, HistoricalLearning
- Classes: HistoricalLearningStatus, HistoricalLearningContext, HistoricalLearningResolver
- Functions: _required_text, _aware, _finite, _ratio, _parse_timestamp, _symbol_from_identifier, _historical_asset_class, _item_asset_class, _item_symbol, _horizon_matches, _regime_matches, _numeric_values

## `cio/models.py`
- Terms: CandidateDecisionRecord, Valuation
- Classes: CandidateAssetClass, CIOAction, SpecialistRole, SpecialistPosition, EvidenceDependency, ScenarioAdjustment, CapitalAlternativeComparison, PriorDecisionContext, ThesisState, EvidenceQuality, CandidateInstrument, PayoffDistributionPoint, CandidateDecisionRecord, MaterialDissent, SpecialistReturnAdjustment, ReturnReconciliation, CIODecision
- Functions: _required_text, _aware, _finite, _ratio, _text_tuple

## `cio/persistence.py`
- Terms: CandidateDecisionRecord, Valuation, LivingThesis
- Classes: CIOJournalEventType, CIOJournalIntegrityError, CIOJournalEvent, SQLiteCIOJournal
- Functions: _required_text, _aware, _canonical_json, _code_version, serialize_candidate_decision, serialize_opportunity_queue, serialize_specialist_packet, serialize_cio_decision, serialize_thesis_snapshot, serialize_thesis_review

## `cio/policy_governance.py`
- Terms: Valuation
- Classes: PolicyVersionStatus, PolicyPerformanceEvidence, PolicyVersionCandidate, PolicyPromotionPolicy, PolicyPromotionDecision, ChampionChallengerRegistry
- Functions: _text, _aware, _number

## `cio/policy_matrix.py`
- Terms: CandidateDecisionRecord
- Classes: DecisionPolicyProfile, DecisionPolicyMatrix
- Functions: _ratio

## `cio/reconciliation.py`
- Terms: CandidateDecisionRecord, Valuation
- Classes: SpecialistReconciliationPolicy, SpecialistReturnReconciler
- Functions: none

## `cio/robustness.py`
- Terms: CandidateDecisionRecord
- Classes: RobustDecisionPolicy, RobustCandidateAssessment, RobustCandidateAssessor
- Functions: _finite

## `cio/service.py`
- Terms: CandidateDecisionRecord
- Classes: CIOSynthesisPolicy, ChiefInvestmentOfficer
- Functions: none

## `cio/universe.py`
- Terms: package inventory
- Classes: UniverseDisposition, UniverseAssessment, RecommendationUniversePolicy
- Functions: none

## `committee/__init__.py`
- Terms: CandidateDecisionRecord
- Classes: none
- Functions: none

## `committee/cio.py`
- Terms: CandidateDecisionRecord
- Classes: none
- Functions: none

## `committee/consensus.py`
- Terms: package inventory
- Classes: CommitteeConsensus
- Functions: none

## `committee/decision_discipline.py`
- Terms: package inventory
- Classes: DissentDisposition, NoActionReason, StructuredDissent, DissentRegister, NoActionDecision
- Functions: _required_text, _aware_datetime, _text_tuple

## `committee/meeting.py`
- Terms: package inventory
- Classes: CommitteeMeeting, InvestmentCommittee
- Functions: none

## `committee/member.py`
- Terms: package inventory
- Classes: CommitteeMember
- Functions: none

## `committee/opinion.py`
- Terms: package inventory
- Classes: CommitteeOpinion
- Functions: _required_text, _text_tuple, _confidence

## `committee/regime_governance.py`
- Terms: Valuation
- Classes: RegimeGovernanceOutcome, RegimeGovernancePolicy, RegimeCommitteeDecision, RegimeGovernanceWorkflow
- Functions: build_regime_recommendation

## `committee/specialists.py`
- Terms: CandidateDecisionRecord, Valuation, HistoricalLearning
- Classes: MacroSpecialistContext, MarketSpecialistContext, ForecastScenarioAssessment, CrossAssetForecastSpecialistContext, AssetValuationSpecialistContext, PortfolioSpecialistContext, CandidateSpecialistContext, SpecialistGovernancePolicy, IndependentSpecialistService
- Functions: _required_text, _aware, _ratio, _bounded, _text_tuple, _position

## `committee/workflow.py`
- Terms: package inventory
- Classes: InstitutionalDecisionWorkflow
- Functions: none

## `company/analysis.py`
- Terms: Valuation
- Classes: CompanyAnalysisPolicy, CompanyAnalysisEngine
- Functions: _clip, _available, _average_score, _metric_tuple, _evidence, _risks

## `company/candidate.py`
- Terms: CandidateDecisionRecord, Valuation
- Classes: CompanyExpectedReturnPolicy, CompanyCandidateBuilder
- Functions: _clip

## `company/models.py`
- Terms: Valuation
- Classes: FinancialMetric, CompanyFactor, NormalizedAnnualFinancials, FinancialHistory, CompanyMarketSnapshot, CompanyRegimeContext, CompanyFactorAssessment, CompanyAnalysis
- Functions: _required_text, _aware, _finite, _optional_finite, _text_tuple, _safe_divide

## `company/normalization.py`
- Terms: package inventory
- Classes: CompanyFactNormalizer
- Functions: _fact_identifier, _fiscal_year, _is_annual_duration

## `data/__init__.py`
- Terms: PriceBar, MarketDataProvider
- Classes: none
- Functions: none

## `data/decision_information.py`
- Terms: package inventory
- Classes: DecisionInformationError, InformationQualityState, InformationSourceType, PortfolioImpactChannel, InformationProvenance, DecisionInformationRecord, PortfolioInformationImpact, DecisionInformationProvider, CurrentEventPortfolioAnalyzer
- Functions: _text, _optional_text, _aware, _texts, _ratio

## `data/derivative_market.py`
- Terms: Valuation
- Classes: DerivativeDataError, DerivativeContractType, OptionRight, ExerciseStyle, DerivativeContractRecord, MarginRequirementRecord, OptionQuoteRecord, VolatilitySurfacePoint, VolatilitySurfaceSnapshot, DerivativeDataCertificationReport
- Functions: _text, _aware, _boolean, _finite_positive, _normal_cdf, _black_scholes_price, _implied_volatility, build_volatility_surface, certify_derivative_data

## `data/filing.py`
- Terms: package inventory
- Classes: FilingProviderError, FilingQuery, FilingRecord, CompanyFact, FilingProvider
- Functions: _required_text, _aware_datetime

## `data/market.py`
- Terms: PriceBar, MarketDataProvider
- Classes: MarketDataError, MarketDataType, BarInterval, TradeSide, CorporateActionType, MarketDataProvenance, MarketDataQuery, MarketQuote, MarketTrade, PriceBar, FundingRate, OpenInterest, CorporateAction, MarketDataBatch, CanonicalMarketDataProvider
- Functions: _required_text, _optional_text, _aware_datetime, _number, _normalize_record_identity

## `data/multi_asset_universe.py`
- Terms: package inventory
- Classes: MultiAssetUniverseBuilder
- Functions: _candidate_asset_class, _candidate_exposure_class, _earliest

## `data/observation.py`
- Terms: package inventory
- Classes: DataQualityState, AvailabilityBasis, DataFrequency, ObservationTrend, Transformation, ObservationProvenance, NormalizedObservation
- Functions: _required_text, _aware_datetime, _date_only, _optional_number

## `data/provider.py`
- Terms: package inventory
- Classes: ProviderError, SeriesSpecification, ObservationQuery, ObservationProvider
- Functions: none

## `data/provider_dataset.py`
- Terms: package inventory
- Classes: ProviderDatasetError, ProviderDatasetType, ProviderDatasetQuery, ProviderDatasetSnapshot, ProviderDatasetProvider
- Functions: _text, _aware, _json_payload

## `data/security.py`
- Terms: package inventory
- Classes: SecurityMasterError, AssetClass, InstrumentType, IdentifierScheme, TradingCalendar, InstrumentIdentifier, Issuer, Instrument, VenueListing, SecurityMasterSnapshot
- Functions: normalize_cik, _required_text, _optional_text, _aware_datetime, _validate_identifiers, _validate_tuple, _require_unique

## `data/security_master.py`
- Terms: Valuation
- Classes: SecurityEntityType, ListingStatus, SecurityMasterActionType, SecurityMasterUniverseMembership, SecurityMasterCoverage, IssuerRecord, InstrumentRecord, IdentifierAssignment, ListingRecord, SecurityMasterAction, PointInTimeSecurityMasterSnapshot, SecurityMasterCatalog, SecurityMasterMarketMetrics, Version1UniverseConstituent, Version1UniverseExclusion, Version1UniverseSnapshot, Version1UniverseBuilder
- Functions: _required_text, _aware, _optional_aware, _finite, _interval, _contains, _latest_temporal, _latest_available, _candidate_asset_class, _candidate_exposure_class, _earliest

## `data/security_master_certification.py`
- Terms: package inventory
- Classes: ProviderCertificationDecision, ProviderCertificationScenarioKind, ProviderCapabilityManifest, ProviderCertificationScenario, ProviderCertificationScenarioResult, ProviderCertificationReport, ProviderCertificationHarness, ProviderCertificationIntegrityError, ProviderCertificationEvent, SQLiteProviderCertificationStore
- Functions: _required_text, _aware, _finite, _canonical_json, scenario_from_payload, report_to_payload, _manifest_payload, manifest_from_payload, _scenario_result_payload, _scenario_result_from_payload, _report_payload, _report_from_payload, _report_hash

## `data/security_master_ingestion.py`
- Terms: Valuation
- Classes: SecurityMasterActivationMode, SecurityMasterIngestionDisposition, SecurityMasterOperationType, SecurityMasterProviderError, SecurityMasterReconciliationError, SecurityMasterActivationError, SecurityMasterIngestionQuery, SecurityMasterCatalogDelivery, SecurityMasterProvider, SecurityMasterActivationPolicy, SecurityMasterQualityReport, SecurityMasterIngestionResult, SecurityMasterActivationRecord, SecurityMasterOperationalStatus, SecurityMasterOperationEvent, SQLiteSecurityMasterOperationalStore, SecurityMasterIngestionService, SecurityMasterReconciliationPolicy, SecurityMasterReconciliationReport, ReconciledSecurityMaster, SecurityMasterReconciler, ReconciledSecurityMasterProvider
- Functions: _required_text, _aware, _finite, _ratio, _canonical_json, _identifier_semantic, _issuer_record_semantic, _instrument_record_semantic, _identifier_assignment_semantic, _listing_record_semantic, _action_semantic, _reconciled_coverage, _quality_payload, _quality_from_payload, _ingestion_payload, _ingestion_from_payload, _activation_payload, _activation_from_payload, _operation_hash

## `data/security_master_store.py`
- Terms: package inventory
- Classes: SecurityMasterIntegrityError, SecurityMasterCatalogEvent, SQLiteSecurityMasterStore
- Functions: _aware, _required_text, _canonical_json, _content_hash, serialize_security_master_catalog, deserialize_security_master_catalog, _coverage_payload, _coverage_from_payload, _identifier_payload, _identifier_from_payload, _issuer_payload, _issuer_from_payload, _instrument_payload, _instrument_from_payload, _temporal_payload, _issuer_record_payload, _issuer_record_from_payload, _instrument_record_payload, _instrument_record_from_payload, _identifier_assignment_payload, _identifier_assignment_from_payload, _listing_record_payload, _listing_record_from_payload, _action_payload, _action_from_payload

## `delivery/canonical_alerts.py`
- Terms: Valuation
- Classes: CanonicalAlertEvent, CanonicalAlertPlanningResult, CanonicalAlertPlanner
- Functions: _required_text, _aware, _value, events_from_canonical_cycle

## `evaluation/__init__.py`
- Terms: Valuation
- Classes: none
- Functions: none

## `evaluation/calibration.py`
- Terms: Valuation
- Classes: CalibrationDimension, CalibrationMetric, DecisionCalibrationSuite, DecisionCalibrationSuiteBuilder
- Functions: none

## `evaluation/decision_learning.py`
- Terms: Valuation
- Classes: DecisionLearningState, DecisionLearningObservation, DecisionLearningPolicy, DecisionLearningReport, DecisionLearningSegmentReport, DecisionLearningEvaluator
- Functions: _required_text, _aware, _finite

## `evaluation/decision_quality.py`
- Terms: package inventory
- Classes: ProcessVerdict, DecisionOutcome, DecisionQualityClassification, DecisionQualityReview
- Functions: _required_text, _aware_datetime, _text_tuple

## `evaluation/multi_asset.py`
- Terms: Valuation
- Classes: MultiAssetEvaluationError, MultiAssetEvaluationIntegrityError, MultiAssetEvaluationEventType, MultiAssetReturnObservation, MultiAssetReturnAttribution, MultiAssetPointInTimeEvaluation, MultiAssetPointInTimeEvaluator, SQLiteMultiAssetEvaluationStore
- Functions: _text, _texts, _aware, _number, _currency, _canonical_json

## `evaluation/paper_operation.py`
- Terms: Valuation
- Classes: PaperOperationReadiness, PaperOperationPolicy, PaperOperationObservation, PaperOperationEvidenceReport, PaperOperationEvidenceEvaluator, PaperOperationEvidenceIntegrityError, SQLitePaperOperationEvidenceStore
- Functions: _required_text, _aware, _integer, _number, _ratio, _return, _text_tuple, _canonical_json, _safe_rate, _compound, _maximum_drawdown, observation_from_payload, policy_from_payload

## `evaluation/persistence.py`
- Terms: Valuation
- Classes: none
- Functions: serialize_construction, append_construction, append_evidence_snapshot, append_decision_evaluation, append_calibration_report, append_walk_forward_audit, append_paper_trade_fill

## `evaluation/point_in_time.py`
- Terms: CandidateDecisionRecord, Valuation, LivingThesis
- Classes: EvaluationOutcome, EvaluationProcessVerdict, EvidenceReference, CapitalAlternativeSnapshot, DecisionEvidenceSnapshot, AlternativeRealizedReturn, RealizedDecisionOutcome, DecisionReturnAttribution, PointInTimeDecisionEvaluation, PointInTimeEvaluationPolicy, PointInTimeDecisionEvaluator, CalibrationBucket, ConfidenceCalibrationReport, ConfidenceCalibrator
- Functions: _required_text, _aware, _finite, _text_tuple

## `evaluation/walk_forward.py`
- Terms: Valuation
- Classes: WalkForwardVerdict, PointInTimeResearchRecord, PointInTimeUniverseMembership, WalkForwardFold, WalkForwardAudit, WalkForwardAuditor, PaperTradeFill
- Functions: _required_text, _aware, _finite

## `governance/__init__.py`
- Terms: package inventory
- Classes: none
- Functions: __getattr__

## `governance/asset_class_scope.py`
- Terms: Valuation
- Classes: AssetClassGovernanceError, AssetClassGovernanceIntegrityError, AssetClassApprovalState, TradingSessionModel, CustodySettlementModel, AssetClassCapabilityProfile, AssetClassApproval, AssetClassScopeAssessment, SQLiteAssetClassApprovalStore, AssetClassScopeAuthority
- Functions: _text, _optional_text, _texts, _aware, _positive_number, _canonical_json, _default_instrument_types

## `governance/data_readiness_core.py`
- Terms: Valuation
- Classes: DataReadinessError, MarketDataScopeState, DataDomain, DataProviderRole, AllMarketsDataReadinessState, ProviderDataCapability
- Functions: _text, _texts, _bool

## `governance/data_readiness_evaluator.py`
- Terms: Valuation
- Classes: AllMarketsDataReadinessEvaluator
- Functions: none

## `governance/data_readiness_report.py`
- Terms: package inventory
- Classes: DatasetReadinessAssessment, MarketDataReadinessAssessment, AllMarketsDataReadinessReport
- Functions: none

## `governance/data_readiness_scope.py`
- Terms: package inventory
- Classes: DatasetCoverageRequirement, MarketDataScope, AllMarketsDataManifest
- Functions: none

## `governance/data_readiness_serialization.py`
- Terms: package inventory
- Classes: none
- Functions: _payload_bool, provider_capability_from_payload, market_scope_from_payload, manifest_from_payload, load_data_readiness_manifest

## `governance/decision_information_activation.py`
- Terms: package inventory
- Classes: DecisionInformationActivationError, DecisionInformationActivationIntegrityError, DecisionInformationSourceActivation, SQLiteDecisionInformationActivationStore, DecisionInformationActivationOverlay, DecisionInformationActivationAuthority
- Functions: _text, _aware, _boolean, _canonical_json, _content_hash

## `governance/decision_information_readiness.py`
- Terms: package inventory
- Classes: DecisionInformationReadinessError, DecisionInformationReadinessState, DecisionInformationDomain, DecisionInformationSourceRole, DecisionInformationSourceCapability, DecisionInformationCoverageRequirement, MaximumDecisionInformationManifest, DecisionInformationDomainAssessment, MaximumDecisionInformationReadinessReport, MaximumDecisionInformationReadinessEvaluator
- Functions: _text, _texts, _bool, _payload_bool, source_capability_from_payload, manifest_from_payload, load_maximum_decision_information_manifest

## `governance/eligible_universe.py`
- Terms: package inventory
- Classes: EligibleUniverseError, EligibleUniverseCertificationState, CertifiedEligibleUniversePublication, SQLiteCertifiedEligibleUniverseStore
- Functions: _text, _aware, _texts, _versions, _canonical_json

## `governance/forecast_evidence.py`
- Terms: package inventory
- Classes: ForecastEvidenceError, ForecastEvidenceIntegrityError, ForecastScenario, GovernedForecastEvidence, SQLiteForecastEvidenceStore
- Functions: _text, _aware, _probability, _texts, _versions, _canonical_json

## `governance/market_data_bundle.py`
- Terms: Valuation
- Classes: MarketDataBundleError, ProviderBundleRole, ProviderBindingKind, ProviderBundleMember, ProviderBundleRoleRequirement, AllMarketProviderBundle, ProviderBundleMemberAssessment, ProviderBundleAssessment
- Functions: _text, _texts, _boolean, _configured, _load_json, load_all_market_provider_bundle, _binding_paths, _validate_binding, assess_all_market_provider_bundle

## `governance/paper_decision_approval.py`
- Terms: package inventory
- Classes: PaperDecisionApprovalError, PaperDecisionApprovalIntegrityError, PaperDecisionApprovalState, PaperDecisionApprovalEvent, SQLitePaperDecisionApprovalStore
- Functions: _text, _aware, _canonical_json, canonical_construction_sha256, require_user_approved_paper_decision

## `governance/paper_execution_authority.py`
- Terms: package inventory
- Classes: HumanPaperTestEntryAuthorization, CombinedPaperExecutionAuthorization
- Functions: _text, _aware, require_human_paper_test_entry, require_combined_paper_execution_authorization

## `governance/paper_test_entry.py`
- Terms: package inventory
- Classes: PaperTestEntryGovernanceError, PaperTestEntryIntegrityError, ProcessFreezeState, PaperTestEligibilityState, PaperTestEntryDecisionState, PaperTestGovernanceEventType, InvestmentProcessFreeze, ControlledPaperTestEligibilityPackage, ControlledPaperTestEntryDecision, PaperTestEntryPackageAssembler, SQLitePaperTestEntryGovernanceStore
- Functions: _text, _texts, _aware, _digest, _canonical_json, canonical_process_bundle_sha256

## `governance/paper_trading_launch.py`
- Terms: Valuation
- Classes: PaperTradingLaunchError, PaperTradingLaunchIntegrityError, PaperTradingLaunchState, PaperTradingControlState, PaperTradingLaunchPolicy, PaperTradingLaunchEvidence, PaperTradingLaunchReport, PaperTradingLaunchEvaluator, SQLitePaperTradingLaunchStore, PaperTradingControlEvent, SQLitePaperTradingControlStore, PaperExecutionAuthorization
- Functions: _text, _texts, _aware, _count, _number, _canonical_json, require_paper_execution_authorization

## `governance/paper_trading_launch_authority.py`
- Terms: package inventory
- Classes: SQLitePaperTradingLaunchStore
- Functions: none

## `governance/product_readiness.py`
- Terms: Valuation
- Classes: ProductTestReadiness, TestReadinessIntegrityError, ProductTestReadinessEvidence, ProductTestReadinessReport, ProductTestReadinessEvaluator, SQLiteProductTestReadinessStore
- Functions: _text, _aware, _texts, _json

## `governance/provider_activation.py`
- Terms: package inventory
- Classes: ProviderActivationError, ProviderActivationIntegrityError, ProviderActivation, SQLiteProviderActivationStore, ProviderActivationOverlay, ProviderActivationAuthority
- Functions: _text, _aware, _boolean, _canonical_json, _content_hash

## `governance/readiness_evidence.py`
- Terms: Valuation
- Classes: ReadinessEvidenceError, ReadinessEvidenceIntegrityError, ReadinessGate, ReadinessGateState, ReadinessEvidenceEventType, ReadinessGateCertification, OperationalReadinessSnapshot, SQLiteReadinessEvidenceStore, ProductTestReadinessEvidenceAssembler
- Functions: _text, _optional_text, _texts, _aware, _count, _json

## `governance/stage_binding_approval.py`
- Terms: package inventory
- Classes: StageBindingApprovalError, StageBindingApprovalIntegrityError, StageBindingApprovalState, StageBindingApproval, SQLiteStageBindingApprovalStore
- Functions: _text, _aware, _texts, canonical_binding_payload, stage_binding_sha256, _looks_secret, require_approved_stage_bindings

## `historical_replay/backfill.py`
- Terms: package inventory
- Classes: HistoricalBackfillCoordinator
- Functions: ten_year_window, load_config, coordinator_from_config

## `historical_replay/canonical.py`
- Terms: CandidateDecisionRecord, Valuation
- Classes: ReplayPortfolioState, HistoricalCanonicalContextBuilder, CanonicalHistoricalReplayEngine
- Functions: _clamp, _decision_time, _symbol, _asset_class, _metadata, _price_records, _average_dollar_volume, _cash_return, _latest_series, _macro_context, load_replay_config

## `historical_replay/canonical_runtime.py`
- Terms: HistoricalLearning
- Classes: EfficientCanonicalHistoricalReplayEngine
- Functions: _decision_time, _replay_relevant, _enum_value

## `historical_replay/canonical_runtime_v4.py`
- Terms: HistoricalLearning
- Classes: HorizonAlignedCanonicalHistoricalReplayEngine
- Functions: _cutoff_time, _decision_value

## `historical_replay/canonical_runtime_v5.py`
- Terms: package inventory
- Classes: MacroCompleteCanonicalHistoricalReplayEngine
- Functions: _cutoff_datetime

## `historical_replay/features.py`
- Terms: package inventory
- Classes: none
- Functions: _price_records, market_features, event_features

## `historical_replay/http.py`
- Terms: package inventory
- Classes: HttpResponse, HttpClient
- Functions: none

## `historical_replay/models.py`
- Terms: package inventory
- Classes: HistoricalRecord, SourceResult, BackfillReport
- Functions: utc_now, parse_timestamp, iso_timestamp, canonical_json

## `historical_replay/replay.py`
- Terms: package inventory
- Classes: ShadowDecision, ShadowReplayEngine
- Functions: replay_dates

## `historical_replay/runtime.py`
- Terms: package inventory
- Classes: none
- Functions: _boolean, run_once, run_loop

## `historical_replay/sources.py`
- Terms: package inventory
- Classes: HistoricalSource
- Functions: build_sources

## `historical_replay/sources_market.py`
- Terms: package inventory
- Classes: FredSource, CoinbaseSource, StooqSource
- Functions: _chunks

## `historical_replay/sources_public.py`
- Terms: package inventory
- Classes: WorldBankSource, FederalRegisterSource, SecCompanyFactsSource, CftcSource, TreasuryFiscalDataSource, GdeltSource
- Functions: _iso_date

## `historical_replay/store.py`
- Terms: package inventory
- Classes: HistoricalStore
- Functions: none

## `institutional_market/data_enablement.py`
- Terms: Valuation
- Classes: DataEnablementStatus, ProviderCapability, DataEnablementReport
- Functions: evaluate_production_data

## `institutional_market/walk_forward.py`
- Terms: Valuation
- Classes: ShadowDecisionObservation, WalkForwardCalibrationReport
- Functions: evaluate_walk_forward

## `intelligence/__init__.py`
- Terms: TechnicalMomentum, Valuation, AnalyticalEngineResult
- Classes: none
- Functions: __getattr__, __dir__

## `intelligence/analytical_engine.py`
- Terms: AnalyticalEngineResult
- Classes: EngineDirection, EngineDataStatus, EngineEvidence, AnalyticalEngineResult
- Functions: _text, _aware, _strings

## `intelligence/briefing.py`
- Terms: Valuation
- Classes: CIOBriefing
- Functions: none

## `intelligence/business_cycle.py`
- Terms: Valuation, AnalyticalEngineResult
- Classes: BusinessCycleComponent, BusinessCycleScoringMode, BusinessCycleLoadState, BusinessCycleSeriesRequest, BusinessCycleSeriesLoad, BusinessCycleRun, BusinessCycleEngine
- Functions: _clip, _quality_weight, _score_request, _direction, _phase_description, _transmission, build_fred_business_cycle_engine

## `intelligence/cio.py`
- Terms: package inventory
- Classes: GuidanceSynthesizer, ChiefInvestmentOfficer
- Functions: none

## `intelligence/cio_guidance.py`
- Terms: package inventory
- Classes: ScenarioProbability, ConfidenceScores, ChangeCondition, CIOGuidance
- Functions: none

## `intelligence/committee_adjustment.py`
- Terms: Valuation
- Classes: AdjustmentCategory, ScoreAdjustment, AdjustmentSet
- Functions: none

## `intelligence/committee_adjustment_engine.py`
- Terms: package inventory
- Classes: AdjustmentPolicy, AdjustmentOutcome, AdjustmentEngine
- Functions: none

## `intelligence/committee_assessment.py`
- Terms: package inventory
- Classes: CommitteeAssessment
- Functions: none

## `intelligence/committee_framework.py`
- Terms: package inventory
- Classes: DecisionThresholds, DecisionFramework
- Functions: none

## `intelligence/committee_member.py`
- Terms: package inventory
- Classes: CommitteeMember
- Functions: none

## `intelligence/committee_members/credit.py`
- Terms: package inventory
- Classes: CreditCommitteeMember
- Functions: none

## `intelligence/committee_members/liquidity.py`
- Terms: package inventory
- Classes: LiquidityCommitteeMember
- Functions: none

## `intelligence/committee_members/macro.py`
- Terms: Valuation
- Classes: MacroCommitteeMember
- Functions: none

## `intelligence/committee_members/risk.py`
- Terms: package inventory
- Classes: RiskCommitteeMember
- Functions: none

## `intelligence/committee_members/technical.py`
- Terms: package inventory
- Classes: TechnicalCommitteeMember
- Functions: none

## `intelligence/committee_members/valuation.py`
- Terms: Valuation
- Classes: ValuationCommitteeMember
- Functions: none

## `intelligence/committee_opinion.py`
- Terms: Valuation
- Classes: CommitteeVote, CommitteeRole, CommitteeOpinion, CommitteeOpinionSet
- Functions: _validate_text, _normalize_text_tuple

## `intelligence/committee_statistics.py`
- Terms: package inventory
- Classes: CommitteeStatistics, CommitteeStatisticsCalculator
- Functions: none

## `intelligence/credit_cycle.py`
- Terms: Valuation, AnalyticalEngineResult
- Classes: CreditCycleComponent, CreditCycleScoringMode, CreditCycleLoadState, CreditCycleSeriesRequest, CreditCycleSeriesLoad, CreditCycleRun, CreditCycleEngine
- Functions: _clip, _quality_weight, _score_request, _direction, _phase_description, _transmission, build_fred_credit_cycle_engine

## `intelligence/decision_discipline.py`
- Terms: Valuation
- Classes: ThesisLifecycleStatus, TriggerType, TriggerComparator, EvidenceTrustLevel, ShockDirection, TransmissionDirection, FalsificationTrigger, ThesisTransition, ThesisLifecycle, EvidenceTrustAssessment, ScenarioShock, DecisionScenario, TransmissionEdge, CrossAssetTransmissionMap
- Functions: _required_text, _aware_datetime, _score, _text_tuple

## `intelligence/engine_cycle.py`
- Terms: package inventory
- Classes: AnalyticalEngineCycleExecutor
- Functions: none

## `intelligence/engine_store.py`
- Terms: AnalyticalEngineResult
- Classes: SQLiteAnalyticalEngineStore
- Functions: analytical_engine_result_from_dict

## `intelligence/forecast.py`
- Terms: package inventory
- Classes: EconomicScenario, ScenarioForecast, EconomicForecast
- Functions: none

## `intelligence/forecast_engine.py`
- Terms: package inventory
- Classes: ForecastEngine
- Functions: none

## `intelligence/forecast_strategy.py`
- Terms: package inventory
- Classes: ForecastStrategy
- Functions: none

## `intelligence/global_liquidity.py`
- Terms: Valuation, AnalyticalEngineResult
- Classes: LiquidityComponent, LiquidityScoringMode, LiquidityLoadState, LiquiditySeriesRequest, LiquiditySeriesLoad, GlobalLiquidityRun, GlobalLiquidityEngine
- Functions: _clip, _quality_weight, _score_request, _direction, _transmission, build_fred_global_liquidity_engine

## `intelligence/governance.py`
- Terms: package inventory
- Classes: GovernanceStatus, IssueSeverity, VetoType, PositiveConclusionCeiling, MultiEngineGovernancePolicy, GovernanceIssue, ActiveGovernanceVeto, MultiEngineGovernanceResult, MultiEngineGovernor
- Functions: _required_text, _aware, _score, _positive_int

## `intelligence/governance_store.py`
- Terms: package inventory
- Classes: SQLiteGovernanceStore
- Functions: governance_policy_from_dict, governance_result_from_dict

## `intelligence/investment_committee.py`
- Terms: Valuation
- Classes: InvestmentCommittee
- Functions: none

## `intelligence/investment_committee_consensus.py`
- Terms: package inventory
- Classes: InvestmentCommitteeConsensus
- Functions: none

## `intelligence/investment_committee_decision.py`
- Terms: package inventory
- Classes: InvestmentCommitteeDecision
- Functions: none

## `intelligence/investment_committee_report.py`
- Terms: package inventory
- Classes: CommitteeReportEntry, InvestmentCommitteeReport
- Functions: _validate_text, _validate_text_tuple

## `intelligence/investment_committee_report_generator.py`
- Terms: package inventory
- Classes: InvestmentCommitteeReportGenerator
- Functions: none

## `intelligence/investment_committee_result.py`
- Terms: package inventory
- Classes: InvestmentCommitteeResult
- Functions: none

## `intelligence/investment_policy.py`
- Terms: package inventory
- Classes: InvestmentPolicy
- Functions: none

## `intelligence/liquidity_cycle.py`
- Terms: package inventory
- Classes: LiquidityAwareCycleExecutor
- Functions: none

## `intelligence/market_breadth.py`
- Terms: PriceBar, MarketDataProvider, AnalyticalEngineResult
- Classes: MarketBreadthComponent, MarketBreadthLoadState, BreadthUniverseMember, BreadthUniverseSnapshot, MarketBreadthDataProvider, MarketBreadthMemberLoad, MarketBreadthRun, _ComponentResult, UnavailableMarketBreadthProvider, JSONMarketBreadthProvider, MarketBreadthEngine
- Functions: build_configured_market_breadth_engine, _direction, _transmission, _deduplicate_bars, _bar_is_stale, _aggregate_quality, _quality_state, _parse_datetime, _parse_optional_datetime, _require_aware, _clip

## `intelligence/metadata.py`
- Terms: package inventory
- Classes: DocumentStatus, DocumentMetadata
- Functions: utc_now

## `intelligence/models.py`
- Terms: package inventory
- Classes: MarketSnapshot, CIODecision
- Functions: none

## `intelligence/normalization.py`
- Terms: Valuation, AnalyticalEngineResult
- Classes: ScoreOrientation, EngineNormalizationPolicy, NormalizedEngineAssessment, MultiEngineNormalizationBundle, MultiEngineNormalizer
- Functions: _policy, _aware, _bounded_int, _strings

## `intelligence/normalization_store.py`
- Terms: package inventory
- Classes: SQLiteNormalizationStore
- Functions: normalization_bundle_from_dict

## `intelligence/observation.py`
- Terms: package inventory
- Classes: ObservationCategory, Trend, IndicatorId, Observation, ObservationSet
- Functions: none

## `intelligence/observation_adapter.py`
- Terms: package inventory
- Classes: none
- Functions: to_normalized_observation

## `intelligence/pipeline.py`
- Terms: package inventory
- Classes: none
- Functions: build_allocation, run_intelligence, save_decision

## `intelligence/portfolio_manager.py`
- Terms: package inventory
- Classes: TradeRecommendation
- Functions: load_model_portfolios, determine_model, build_trade_recommendations

## `intelligence/provider.py`
- Terms: package inventory
- Classes: none
- Functions: load_sample_snapshot

## `intelligence/rebalancer.py`
- Terms: package inventory
- Classes: RebalanceAction
- Functions: calculate_rebalance

## `intelligence/recommendation.py`
- Terms: package inventory
- Classes: RecommendationLevel, RecommendationAction, RecommendationMagnitude, RecommendationStatus, ExpectedReturn, ExpectedRisk, InvestmentRecommendation, RecommendationSet
- Functions: none

## `intelligence/recommendation_builder.py`
- Terms: package inventory
- Classes: RecommendationBuilder
- Functions: none

## `intelligence/recommendation_engine.py`
- Terms: package inventory
- Classes: RecommendationEngine
- Functions: none

## `intelligence/recommendation_rules.py`
- Terms: Valuation
- Classes: RecommendationRules
- Functions: none

## `intelligence/reflection.py`
- Terms: Valuation
- Classes: CIOReflection
- Functions: none

## `intelligence/regime.py`
- Terms: package inventory
- Classes: none
- Functions: determine_regime, evaluate_economic_regime

## `intelligence/regime_pipeline.py`
- Terms: package inventory
- Classes: SeriesLoadState, RegimeSeriesRequest, RegimeSeriesLoad, InstitutionalRegimeRun, InstitutionalRegimePipeline
- Functions: build_fred_regime_pipeline

## `intelligence/report_formatter.py`
- Terms: package inventory
- Classes: ReportFormatter
- Functions: none

## `intelligence/risk.py`
- Terms: AnalyticalEngineResult
- Classes: RiskDataError, RiskMetric, RiskLoadState, RiskObservation, RiskDataset, RiskDataProvider, RiskMetricLoad, RiskRun, _Component, UnavailableRiskProvider, JSONRiskProvider, RiskEngine
- Functions: build_configured_risk_engine, risk_source_readiness, _percentile, _quality_state, _parse_datetime, _parse_date, _require_aware, _clip

## `intelligence/state.py`
- Terms: package inventory
- Classes: Strength, Direction, EconomicState
- Functions: none

## `intelligence/state_engine.py`
- Terms: package inventory
- Classes: EconomicStateEngine
- Functions: none

## `intelligence/strategies/rule_based.py`
- Terms: package inventory
- Classes: RuleBasedForecastStrategy
- Functions: none

## `intelligence/synthesis_store.py`
- Terms: package inventory
- Classes: SQLiteSynthesisStore
- Functions: synthesis_policy_from_dict, synthesis_result_from_dict

## `intelligence/synthesis_weights.py`
- Terms: Valuation
- Classes: MissingWeightPolicy, SynthesisStatus, EngineSynthesisWeight, SynthesisWeightPolicy, WeightedEngineContribution, MultiEngineSynthesisResult, MultiEngineSynthesizer
- Functions: _required_text, _aware, _basis_points, _score, _round_score

## `intelligence/technical_momentum.py`
- Terms: TechnicalMomentum, Valuation, PriceBar, AnalyticalEngineResult
- Classes: TechnicalMomentumDataError, TechnicalMomentumComponent, TechnicalMomentumLoadState, TechnicalMomentumDataset, TechnicalMomentumDataProvider, TechnicalMomentumComponentLoad, TechnicalMomentumRun, UnavailableTechnicalMomentumProvider, JSONTechnicalMomentumProvider, TechnicalMomentumEngine
- Functions: build_configured_technical_momentum_engine, technical_momentum_source_readiness, _dedupe, _ann_vol, _quality, _dt, _aware, _clip

## `intelligence/theme.py`
- Terms: package inventory
- Classes: ThemeCategory, ThemeDirection, EconomicTheme, ThemeSet
- Functions: none

## `intelligence/theme_engine.py`
- Terms: package inventory
- Classes: ThemeEngine
- Functions: none

## `intelligence/thesis.py`
- Terms: package inventory
- Classes: ThesisDirection, ThesisHorizon, ThesisStatus, InvestmentThesis, InvestmentThesisSet
- Functions: none

## `intelligence/thesis_engine.py`
- Terms: Valuation
- Classes: InvestmentThesisEngine
- Functions: none

## `intelligence/valuation.py`
- Terms: Valuation, AnalyticalEngineResult
- Classes: ValuationDataError, ValuationMetric, ValuationLoadState, ValuationObservation, ValuationDataset, ValuationDataProvider, ValuationMetricLoad, ValuationRun, _Component, UnavailableValuationProvider, JSONValuationProvider, ValuationEngine
- Functions: build_configured_valuation_engine, valuation_source_readiness, _direction, _language, _percentile, _quality_state, _parse_datetime, _parse_date, _require_aware, _format_percent, _clip

## `journal/append_only.py`
- Terms: Valuation
- Classes: JournalEventType, JournalIntegrityError, JournalEvent, SQLiteAppendOnlyJournal
- Functions: _required_text, _aware_datetime, _canonical_json, serialize_regime_run, serialize_decision_quality_review, serialize_regime_committee_decision, serialize_market_change_assessment, serialize_portfolio_fit_decision

## `operations/__init__.py`
- Terms: Valuation
- Classes: none
- Functions: __getattr__

## `operations/all_markets_paper_rehearsal.py`
- Terms: package inventory
- Classes: RehearsalInstrument, _SessionProvider, _QuoteProvider, AllMarketsPaperRehearsalReport
- Functions: _reset_rehearsal_state, _profile, _quote, run_all_markets_paper_rehearsal

## `operations/alpaca_paper_broker.py`
- Terms: package inventory
- Classes: AlpacaPaperBrokerError, AlpacaPaperBrokerIntegrityError, AlpacaPaperBrokerEventType, AlpacaPaperOrderSnapshot, AlpacaPaperFillActivity, AlpacaPaperBrokerReconciliation, AlpacaPaperRoundTripReport, SQLiteAlpacaPaperBrokerStore, AlpacaPaperBrokerExecutor
- Functions: _text, _aware, _timestamp, _number, _canonical_json, _payload_hash, require_alpaca_paper_provider_activation

## `operations/alpaca_paper_round_trip.py`
- Terms: package inventory
- Classes: FeeAwareAlpacaPaperBrokerExecutor
- Functions: _aware, _text, _decimal, _usable_position_value, _available_quantity, _round_down_crypto_quantity

## `operations/backup.py`
- Terms: package inventory
- Classes: BackupError, BackupResult, SQLiteBackupManager
- Functions: _sha256, _verify_database, _text, _canonical_json

## `operations/backup_registry.py`
- Terms: Valuation
- Classes: CanonicalBackupAuthority, CanonicalBackupRegistry
- Functions: build_canonical_backup_registry

## `operations/config.py`
- Terms: Valuation
- Classes: OperationalSettings
- Functions: _boolean, _optional

## `operations/crypto_venue_validation.py`
- Terms: package inventory
- Classes: CryptoVenuePairAssessment, CryptoVenueValidationReport
- Functions: _quote, validate_crypto_venues

## `operations/daily_leases.py`
- Terms: package inventory
- Classes: DailyOperationLeaseError, DailyOperationLeaseLost, DailyOperationLeaseGrant, StageFencingContext, LeasedSQLiteCanonicalDailyOperationsStore, FencedStageRunner, LeasedCanonicalDailyOperationsOrchestrator
- Functions: _text, _aware, _utc_text, _canonical_json, current_stage_fencing_context, assert_current_stage_fence

## `operations/daily_orchestration.py`
- Terms: Valuation
- Classes: CanonicalDailyStage, DailyOperationStatus, StageStatus, ReconciliationStatus, FailureClassification, DailyOperationEventType, DailyOperationError, DailyOperationIntegrityError, StageExecutionError, StageRetryPolicy, CanonicalDailyOperationRequest, CanonicalDailyStageResult, CanonicalDailyStageRequest, CanonicalDailyOperationResult, CanonicalDailyStageRunner, CallableStageRunner, CommandStageRunner, SQLiteCanonicalDailyOperationsStore, CanonicalDailyOperationsOrchestrator
- Functions: _text, _texts, _aware, _canonical_json, operation_result_to_dict

## `operations/execution_calibration.py`
- Terms: package inventory
- Classes: ExecutionCalibrationError, ExecutionCalibrationState, ExecutionSide, ExecutionCalibrationPolicy, ExecutionCalibrationSample, ExecutionCalibrationReport, ExecutionCalibrationEvaluator
- Functions: _text, _aware, _number, _canonical_json, _percentile, load_execution_calibration_input

## `operations/free_paper_pilot.py`
- Terms: Valuation
- Classes: FreePaperPilotInstrument, FreePaperPilotUniverse, FreePaperPilotReadinessReport
- Functions: _text, _number, load_free_paper_pilot_universe, assess_free_paper_pilot_readiness, validate_pilot_construction, write_pilot_profiles, default_alpaca_client

## `operations/heartbeat.py`
- Terms: package inventory
- Classes: WorkerHeartbeat, WorkerHeartbeatStore
- Functions: none

## `operations/incidents.py`
- Terms: package inventory
- Classes: OperationalIncidentError, OperationalIncidentIntegrityError, OperationalIncidentSeverity, OperationalIncidentState, OperationalIncidentEvent, SQLiteOperationalIncidentStore
- Functions: _text, _texts, _aware, _canonical_json

## `operations/logging.py`
- Terms: package inventory
- Classes: JsonFormatter
- Functions: set_request_id, get_request_id, configure_logging

## `operations/metrics.py`
- Terms: package inventory
- Classes: MetricRegistry
- Functions: _escape

## `operations/middleware.py`
- Terms: package inventory
- Classes: SlidingWindowRateLimiter
- Functions: _harden, install_operational_middleware

## `operations/paper_market_readiness.py`
- Terms: Valuation
- Classes: UniversalPaperMarketReadinessReport
- Functions: _load_binding, assess_universal_paper_market_readiness

## `operations/paper_readiness_status.py`
- Terms: package inventory
- Classes: PaperReadinessObjectiveState, PaperReadinessObjective, PaperReadinessStatusReport, PaperReadinessStatusInputs, PaperReadinessStatusAssembler
- Functions: _text, _aware, _load_object

## `operations/paper_test_campaign.py`
- Terms: package inventory
- Classes: PaperTestCampaignError, PaperTestCampaignIntegrityError, PaperTestCampaignState, FailureScenarioKind, FailureScenarioStatus, CampaignEventType, PaperTestCampaignBaseline, BurnInDayRecord, FailureScenarioRecord, PaperTestCampaignReport, SQLitePaperTestCampaignStore, PaperTestCampaignEvaluator
- Functions: _text, _texts, _aware, _non_negative_int, _positive_int, _canonical_json

## `operations/post_operation.py`
- Terms: package inventory
- Classes: PostOperationReadinessPublication, PostOperationReadinessPublisher
- Functions: _text, _aware

## `operations/provider_backfill.py`
- Terms: package inventory
- Classes: ProviderBackfillError, ProviderBackfillState, ProviderBackfillTask, ProviderBackfillPlan, ProviderBackfillArtifact, ProviderBackfillReport, ProviderBackfillRunner
- Functions: _text, _aware, _canonical_bytes, load_provider_factory, load_provider_backfill_plan

## `operations/provider_reconciliation.py`
- Terms: package inventory
- Classes: ProviderReconciliationError, ProviderReconciliationState, ProviderReconciliationReport, ProviderBackfillReconciler
- Functions: _aware, _text, _load_object, _parse_timestamp, _payload_hash, _payload_item_count

## `operations/readiness.py`
- Terms: package inventory
- Classes: OperationalReadinessAssemblyPolicy, OperationalReadinessAssemblyResult, OperationalReadinessAssembler
- Functions: _text, _aware

## `operations/recovery_drill.py`
- Terms: package inventory
- Classes: RecoveryDrillError, RecoveryDrillIntegrityError, RecoveryDrillStatus, RecoveryLineageProbe, RecoveryDrillExpectation, RecoveryDrillReport, SQLiteRecoveryDrillStore, CanonicalRecoveryDrill
- Functions: _text, _aware, _non_negative, _canonical_json

## `operations/release_validation.py`
- Terms: package inventory
- Classes: ReleaseValidationError, ReleaseValidationStep, ReleaseValidationStepResult, ReleaseValidationRunner
- Functions: _bounded

## `operations/resilience.py`
- Terms: Valuation
- Classes: ResilienceExerciseKind, ResilienceExerciseStatus, ResilienceExerciseScenario, ResilienceExerciseOutcome, ResilienceExercisePolicy, ResilienceExerciseReport, ResilienceExerciseProvider, ResilienceExerciseHarness, ResilienceExerciseIntegrityError, SQLiteResilienceExerciseStore
- Functions: _required_text, _aware, _positive_int, _text_tuple, _canonical_json, scenario_from_payload, policy_from_payload

## `operations/slo.py`
- Terms: Valuation
- Classes: OperationalSLOName, OperationalSLOStatus, FullUniverseCycleStatus, OperationalSLOPolicy, FullUniverseCycleRecord, SecurityMasterSLOObservation, ThesisSLOObservation, DecisionEvaluationSLOObservation, OperationalSLOInputs, OperationalSLOComponent, OperationalSLOSnapshot, OperationalSLOEvaluator, OperationalSLOIntegrityError, SQLiteOperationalSLOStore, SQLiteOperationalSLOSource, OperationalSLOService
- Functions: _required_text, _aware, _non_negative_number, _non_negative_integer, _canonical_json, operational_slo_policy_from_settings, build_operational_slo_service

## `operations/stage_bindings.py`
- Terms: package inventory
- Classes: StageBindingError, StageBindingTimeout, StageCommandBinding, StageBindingExecution
- Functions: _text, _field, load_stage_bindings, validate_stage_bindings, execute_stage_binding

## `operations/universal_paper_availability.py`
- Terms: package inventory
- Classes: UniversalPaperAssetClassCapability, UniversalPaperAssetClassScope, UniversalPaperAvailabilityReport
- Functions: _text, _texts, load_universal_paper_asset_class_scope, assess_universal_paper_availability

## `opportunity/engine.py`
- Terms: CandidateDecisionRecord
- Classes: OpportunityQualificationPolicy, OpportunityEngine
- Functions: _clamp

## `opportunity/models.py`
- Terms: CandidateDecisionRecord
- Classes: AlternativeKind, QualificationOutcome, AnalysisLane, AlternativeUse, OpportunityRankingInput, OpportunitySetContext, CandidateQualification, ScoreComponent, RankedOpportunity, OpportunityQueue
- Functions: _required_text, _finite

## `personal_cio/brief_service.py`
- Terms: Valuation, AnalyticalEngineResult
- Classes: none
- Functions: _default_analytical_database, _latest_analytical_results, _attach_analytical_context, build_personal_cio_brief

## `portfolio/__init__.py`
- Terms: Valuation
- Classes: none
- Functions: none

## `portfolio/construction_engine.py`
- Terms: package inventory
- Classes: _AssetState, PortfolioConstructionEngine
- Functions: none

## `portfolio/construction_models.py`
- Terms: CandidateDecisionRecord
- Classes: ConstructionStatus, ConstructionMode, TradeSide, ExposureLimit, PortfolioConstructionPolicy, PortfolioAsset, ConstructionIntent, PortfolioScenario, PortfolioScenarioMetrics, PortfolioConstructionRequest, TradeProposal, ConstraintCheck, PortfolioConstructionResult
- Functions: _required_text, _optional_text, _aware, _finite, _loading_tuple

## `portfolio/derivative_lifecycle.py`
- Terms: package inventory
- Classes: DerivativeLifecycleProfile, DerivativeLifecyclePolicy, DerivativeLifecycleAssessment, DerivativeLifecycleAuthority
- Functions: _text, _aware, _number

## `portfolio/execution.py`
- Terms: Valuation
- Classes: MarketSessionStatus, PaperOrderStatus, PaperExecutionStatus, PaperExecutionEventType, PaperExecutionError, PaperExecutionIntegrityError, PaperExecutionPolicy, MarketSession, PaperQuote, PaperPosition, PaperPortfolioState, PaperOrder, PaperFill, PaperReconciliation, PaperExecutionBatch, MarketSessionProvider, PaperQuoteProvider, PaperExecutionOperationalEvent, SQLitePaperExecutionStore, PaperExecutionOrchestrator
- Functions: _text, _aware, _number, _canonical_json, position_to_dict, portfolio_to_dict, order_to_dict, fill_to_dict, reconciliation_to_dict, batch_to_dict, portfolio_from_dict, order_from_dict, fill_from_dict, reconciliation_from_dict, batch_from_dict

## `portfolio/execution_eligibility.py`
- Terms: package inventory
- Classes: ExecutionEligibilityError, ExecutionEligibilityEvidence, CertifiedExecutionEligibilityAuthority
- Functions: _text, _aware

## `portfolio/fit.py`
- Terms: package inventory
- Classes: PortfolioFitOutcome, PortfolioFitPolicy, PortfolioFitDecision, PortfolioFitGate
- Functions: _required_text, _aware_datetime, _bounded_ratio

## `portfolio/integrity_specialist.py`
- Terms: Valuation
- Classes: PortfolioIntegrityDisposition, PortfolioIntegrityCertification, PortfolioValuationExecutionIntegritySpecialist, SQLitePortfolioIntegrityCertificationStore
- Functions: none

## `portfolio/models.py`
- Terms: package inventory
- Classes: AssetBucket, AssetBucketLimit, PortfolioPosition, PortfolioSnapshot, PortfolioMandate, PortfolioProposal
- Functions: _required_text, _aware_datetime, _ratio, _text_tuple

## `portfolio/multi_asset_controls.py`
- Terms: package inventory
- Classes: MultiAssetConstructionError, MultiAssetInstrumentProfile, MultiAssetConstructionPolicy, GovernedMultiAssetConstructionEngine
- Functions: _text, _positive_number, _number

## `portfolio/multi_asset_execution.py`
- Terms: package inventory
- Classes: MultiAssetExecutionError, MultiAssetExecutionIntegrityError, InstrumentSessionStatus, MultiAssetOrderStatus, MultiAssetExecutionStatus, MultiAssetExecutionEventType, MultiAssetExecutionPolicy, InstrumentSession, MultiAssetQuote, InstrumentSessionProvider, MultiAssetQuoteProvider, MultiAssetPaperFill, MultiAssetOrderResult, MultiAssetExecutionReconciliation, MultiAssetExecutionBatch, SQLiteMultiAssetPaperExecutionStore, MultiAssetPaperExecutionOrchestrator
- Functions: _text, _optional_text, _aware, _number, _signed_number, _currency, _canonical_json, fill_to_dict, batch_to_dict, batch_from_dict

## `portfolio/multi_asset_execution_retry.py`
- Terms: Valuation
- Classes: MultiAssetPaperExecutionOrchestrator
- Functions: none

## `portfolio/opportunity_cost.py`
- Terms: package inventory
- Classes: FundingSourceType, OpportunityCostPolicy, FundingCandidate, CapitalFundingSource, OpportunityCostAssessment
- Functions: _required_text, _weight, assess_opportunity_cost, opportunity_cost_to_dict

## `portfolio/performance.py`
- Terms: Valuation
- Classes: PortfolioPerformanceError, PortfolioValuationPolicy, CurrencyRateMark, CurrencyRateProvider, PositionValuationChange, PortfolioValuationReport, PortfolioMarkToMarketService, PortfolioCashFlowKind, PortfolioCashFlowBooking, PortfolioCashFlowService, PortfolioAccountingMigrationReport, PortfolioAccountingMigrationService, PortfolioPositionAdjustment, PortfolioPositionAdjustmentService
- Functions: _text, _aware, _number

## `portfolio/performance_integrity.py`
- Terms: Valuation
- Classes: PortfolioMarkToMarketService
- Functions: none

## `portfolio/scenario_authority.py`
- Terms: package inventory
- Classes: GovernedPortfolioScenario, GovernedPortfolioScenarioSet, PortfolioScenarioAuthority
- Functions: _text, _aware, _number

## `portfolio/state.py`
- Terms: Valuation
- Classes: CanonicalCurrencyBalance, CanonicalPortfolioPosition, CanonicalImplementationEvent, CanonicalPortfolioSnapshot, CanonicalPortfolioIntegrityError, CanonicalPortfolioCompatibilityError, CanonicalPortfolioInitialization, SQLiteCanonicalPortfolioStore
- Functions: _text, _optional_text, _aware, _optional_aware, _signed_number, _number, _currency, _canonical_json, currency_balance_to_dict, position_to_dict, event_to_dict, snapshot_to_dict, snapshot_from_dict, snapshot_summary, snapshot_details, canonical_initial_snapshot, _archive_portfolio_database, ensure_canonical_portfolio_store

## `production_smoke_test.py`
- Terms: Valuation
- Classes: none
- Functions: _utc_now, _aware_utc, _data_root, pre_restart_snapshot_path, latest_result_path, _atomic_json, _load_json, _parse_timestamp, _age_seconds, _process_start_marker, _database_summary, _database_set, _rows_preserved, capture_pre_restart_snapshot, load_pre_restart_snapshot, _latest_execution_attempt, _default_provider_probe, _default_backup_probe, create_encrypted_backup_now, evaluate_runtime_smoke_test

## `providers/alpaca_paper.py`
- Terms: package inventory
- Classes: AlpacaPaperProviderError, AlpacaPaperSettings, AlpacaPaperClient, AlpacaPaperSessionProvider, AlpacaPaperQuoteProvider
- Functions: _text, _environment_value, _environment_values, _timestamp, create_alpaca_paper_client, create_alpaca_paper_session_provider, create_alpaca_paper_quote_provider

## `providers/alpaca_paper_broker.py`
- Terms: package inventory
- Classes: AlpacaPaperOrderRequest, AlpacaPaperApiResponse, AlpacaPaperBrokerClient
- Functions: _text, _positive_decimal, create_alpaca_paper_broker_client

## `providers/configured_dataset.py`
- Terms: package inventory
- Classes: ConfiguredDatasetProviderError, ConfiguredDatasetBinding, ConfiguredDatasetProviderSettings, TransportResponse, ConfiguredDatasetProvider
- Functions: _text, _mapping, _string_tuple, _expand, _lookup, _timestamp, _default_transport, build_from_environment

## `providers/configured_information.py`
- Terms: package inventory
- Classes: ConfiguredDecisionInformationError, ConfiguredDecisionInformationProvider
- Functions: _timestamp, _texts, _record, build_configured_decision_information_provider

## `providers/configured_pipeline.py`
- Terms: package inventory
- Classes: ConfiguredPipelineAdapterError, ConfiguredSecurityMasterProvider, ConfiguredUniverseMetricsProvider, ConfiguredCandidateScreeningProvider
- Functions: _dataset_provider, _metric, build_configured_security_master_provider, build_configured_universe_metrics_provider, build_configured_candidate_screening_provider

## `providers/crypto_venues.py`
- Terms: MarketDataProvider
- Classes: CryptoVenueProviderError, CryptoVenueBinding, CryptoVenueBindingRegistry, _BaseCryptoVenueProvider, CoinbaseExchangeProvider, KrakenSpotProvider
- Functions: load_crypto_venue_bindings, _configured_registry, build_coinbase_exchange_provider, build_kraken_spot_provider

## `providers/databento.py`
- Terms: PriceBar, MarketDataProvider
- Classes: DatabentoProviderError, DatabentoRetrievalPolicy, DatabentoInstrumentBinding, DatabentoBindingRegistry, DatabentoProvider
- Functions: load_databento_bindings, build_databento_provider

## `providers/economic_snapshot.py`
- Terms: package inventory
- Classes: EconomicReadings, EconomicDashboardData
- Functions: clamp, build_live_snapshot, load_dashboard_data, load_best_available_snapshot

## `providers/eodhd.py`
- Terms: PriceBar, MarketDataProvider
- Classes: EODHDProviderError, EODHDRetrievalPolicy, EODHDInstrumentBinding, EODHDBindingRegistry, EODHDProvider
- Functions: load_eodhd_bindings, build_eodhd_provider

## `providers/fred.py`
- Terms: package inventory
- Classes: FREDProviderError, FREDRetrievalPolicy, _PayloadResult, FREDObservation, FREDProvider
- Functions: none

## `providers/fred_cache.py`
- Terms: package inventory
- Classes: FREDCacheRecord, FREDCache, MemoryFREDCache, JsonFREDCache
- Functions: _aware_datetime, fred_cache_key

## `providers/free_connections.py`
- Terms: package inventory
- Classes: FreeProviderConnectionError, FreeProviderConnectionIntegrityError, FreeProviderConnectionState, FreeProviderDefinition, FreeProviderConnectionCatalog, FreeProviderProbeResult, FreeProviderConnectionReport, FreeProviderConnectionVerifier, SQLiteFreeProviderConnectionStore
- Functions: _text, _texts, _aware, _canonical_json, load_free_provider_catalog

## `providers/gleif.py`
- Terms: package inventory
- Classes: GleifProviderError, GleifEntityRecord, GleifProvider
- Functions: _text, _optional_text, _nested

## `providers/market_data.py`
- Terms: MarketDataProvider
- Classes: Quote, MarketDataProvider
- Functions: none

## `providers/mock_market_data.py`
- Terms: MarketDataProvider
- Classes: MockMarketDataProvider
- Functions: none

## `providers/openfigi.py`
- Terms: package inventory
- Classes: OpenFigiProviderError, OpenFigiMappingJob, OpenFigiInstrumentMatch, OpenFigiMappingResult, OpenFigiProvider
- Functions: _text, _optional_text

## `providers/provider_credentials.py`
- Terms: package inventory
- Classes: ProviderCredentialProbeError, EnvironmentCredential, AlphaVantageCredentialProbe, TwelveDataCredentialProbe, DatabentoCredentialProbe, EODHDCredentialProbe
- Functions: _text, environment_credential, configured_environment_names, _json_response

## `providers/public_live_information.py`
- Terms: package inventory
- Classes: PublicLiveInformationError, PublicLiveSourceDefinition, PublicLiveSourceResult, PublicLiveCoverageReport, PublicLiveSourceCatalog, PublicLiveInformationProvider
- Functions: _text, _utc_now, _parse_timestamp, _hash_payload, _safe_summary, source_from_payload, load_public_live_source_catalog

## `providers/public_live_information_extended.py`
- Terms: package inventory
- Classes: ImpactfulPublicLiveInformationProvider
- Functions: _nonempty

## `providers/public_live_information_runtime.py`
- Terms: package inventory
- Classes: GovernedPublicLiveInformationProvider
- Functions: _plain_text, _date_value, _replace_placeholders, _redact

## `providers/sec_edgar.py`
- Terms: package inventory
- Classes: SECEdgarProviderError, SECEdgarProvider
- Functions: none

## `providers/supplemental_quotes.py`
- Terms: package inventory
- Classes: SupplementalQuoteError, SupplementalQuote, SupplementalQuoteCrossCheck, SupplementalQuoteProvider
- Functions: _text, _price

## `reporting/daily_cio.py`
- Terms: LivingThesis
- Classes: DailyCIOStatus, DailyCIOBriefing, DailyCIOBriefingBuilder
- Functions: _required_text, _aware, _text_tuple

## `reporting/decision_replay.py`
- Terms: Valuation
- Classes: DecisionReplayEvent, DecisionReplayPerformance, DecisionReplayStep, DecisionReplay
- Functions: _required_text, _aware, build_decision_replay, decision_replay_to_dict, render_decision_replay_json, render_decision_replay_markdown

## `run_asset_specific_evidence.py`
- Terms: AssetSpecificEvidencePacket
- Classes: none
- Functions: _load, main

## `run_forecast_evidence.py`
- Terms: CandidateForecastSupport
- Classes: none
- Functions: _load, build_parser, _timestamp, main

## `run_multi_asset_attribution.py`
- Terms: Valuation
- Classes: none
- Functions: _payload, build_parser, main

## `run_paper_operation_review.py`
- Terms: Valuation
- Classes: none
- Functions: _timestamp, _json, _observations, main

## `run_portfolio_mark_to_market.py`
- Terms: Valuation
- Classes: none
- Functions: _factory, _load, _profile, _timestamp, build_parser, main

## `run_resilience_exercises.py`
- Terms: Valuation
- Classes: none
- Functions: _json, _provider, _timestamp, main

## `run_slos.py`
- Terms: Valuation
- Classes: none
- Functions: _timestamp, _path, _record_cycle, main

## `run_technical_momentum.py`
- Terms: TechnicalMomentum
- Classes: none
- Functions: _parse_as_of, main

## `run_valuation.py`
- Terms: Valuation
- Classes: none
- Functions: _parse_as_of, main

## `screening/orchestration.py`
- Terms: CandidateDecisionRecord
- Classes: FullUniverseScreeningError, ScreeningEventType, ScreeningDisposition, FullUniverseScreeningRequest, CandidateScreeningDecision, InstrumentScreeningResult, FullUniverseScreeningPublication, FullUniverseScreeningRun, ScreeningEvent, UniverseMetricsProvider, CandidateScreeningProvider, SQLiteFullUniverseScreeningStore, FullUniverseScreeningOrchestrator
- Functions: _required_text, _aware, _non_negative_integer, _canonical_json, candidate_from_payload, _candidate_from_payload

## `tests/cio_test_fixtures.py`
- Terms: CandidateDecisionRecord, Valuation
- Classes: none
- Functions: build_candidate, build_context, build_queue, build_specialist_packet, build_decision

## `tests/test_all_markets_paper_readiness.py`
- Terms: Valuation
- Classes: none
- Functions: test_provider_neutral_dataset_contract_covers_every_readiness_domain, test_repository_is_internally_ready_while_external_activation_fails_closed, test_all_markets_mechanical_rehearsal_executes_every_classified_class, test_complete_external_activation_can_reach_paper_ready

## `tests/test_api.py`
- Terms: Valuation
- Classes: none
- Functions: _snapshot_payload, _create_snapshot_database, _create_portfolio_database, _client, test_health_and_readiness_distinguish_process_from_dependencies, test_required_operational_slos_fail_readiness_and_share_metrics_auth, test_latest_preserves_the_existing_schema_and_honest_status, test_history_is_bounded_and_paginated, test_environment_and_decision_share_canonical_sources, test_replays_expose_references_and_read_only_artifacts, test_portfolio_routes_are_read_only, test_missing_required_store_returns_503_without_affecting_health, test_openapi_contract_is_deterministic_and_has_no_mutation_routes, test_conflicting_replay_identifiers_return_409

## `tests/test_append_only_journal.py`
- Terms: Valuation
- Classes: none
- Functions: _journal, _regime_run, _review, test_regime_run_round_trips_complete_lineage, test_payload_property_returns_a_fresh_copy, test_quality_review_links_to_decision_and_hash_chain, test_database_triggers_reject_update_and_delete, test_hash_chain_detects_out_of_band_tampering, test_events_can_be_filtered_by_aggregate, test_payload_rejects_non_json_numbers

## `tests/test_canonical_alerts.py`
- Terms: Valuation
- Classes: none
- Functions: _account, _result, test_cycle_translates_only_to_canonical_event_topics, test_planner_uses_event_topic_not_score_or_threshold, test_disabled_canonical_topic_is_recorded_as_suppressed, test_scheduler_queues_cycle_events_idempotently, test_active_alert_surfaces_exclude_score_and_conviction_contracts

## `tests/test_canonical_backup_registry.py`
- Terms: Valuation
- Classes: none
- Functions: _database, _environment, _populate_registry, test_registry_covers_active_authorities_and_excludes_retired_names, test_canonical_backup_blocks_when_any_required_authority_is_missing, test_complete_canonical_backup_verifies_and_restores_every_authority, test_production_manager_never_accepts_retired_authorities, test_version_two_manifest_rejects_missing_required_entry, test_registry_environment_override_preserves_logical_identity

## `tests/test_canonical_cio.py`
- Terms: CandidateDecisionRecord, Valuation
- Classes: none
- Functions: _instrument, _candidate, _analysis, _packet, test_candidate_calculates_probability_weighted_and_net_return, test_scenario_probabilities_must_sum_to_one, test_version_one_universe_allows_liquid_us_equity_and_etf, test_version_one_universe_keeps_crypto_and_international_equity_as_evidence, test_short_us_treasury_equivalent_is_eligible_but_long_duration_is_not, test_universe_blocks_stale_illiquid_or_undercovered_direct_candidates, test_specialist_packet_requires_exactly_six_independent_roles, test_only_evidence_officer_can_veto, test_only_portfolio_manager_can_size_or_block_implementation, test_cio_buys_qualified_superior_opportunity, test_supportive_votes_cannot_override_low_expected_return, test_evidence_veto_forces_insufficient_evidence, test_evidence_veto_reduces_an_existing_holding_instead_of_preserving_risk, test_positive_holding_is_reduced_when_a_superior_alternative_exists, test_adverse_specialist_reconciliation_can_block_preliminary_maximum_size, test_portfolio_block_produces_watch_without_position_size, test_high_confidence_dissent_is_preserved_and_prevents_action, test_intelligence_only_asset_cannot_receive_direct_action, test_existing_holding_can_be_increased_reduced_or_exited, test_low_evidence_quality_forces_abstention

## `tests/test_canonical_cio_cycle.py`
- Terms: CandidateDecisionRecord
- Classes: none
- Functions: _candidate, _opportunity_context, _portfolio, _context, _construction_policy, test_successful_etf_cycle_reaches_cio_construction_thesis_and_briefing, test_empty_qualified_queue_produces_no_superior_opportunity, test_equity_without_company_analysis_is_vetoed_as_insufficient_evidence, test_multiple_candidates_compete_for_scarce_cash_in_rank_order, test_specialist_analyses_are_independent_and_complete, test_daily_briefing_answers_five_questions_without_primary_score, test_cycle_rejects_candidate_weight_that_disagrees_with_portfolio, test_cycle_requires_context_for_every_qualified_candidate

## `tests/test_canonical_no_action_learning.py`
- Terms: CandidateDecisionRecord, HistoricalLearning
- Classes: none
- Functions: _price_record, _live_candidate, test_pre_cio_rejections_remain_distinct_and_calibration_scoped, test_outcomes_are_measured_at_stated_decision_horizon, test_learning_input_excludes_policy_only_and_remaps_horizon_value, test_live_resolver_uses_safe_sidecar_and_reports_governance_exclusions

## `tests/test_canonical_product_surfaces.py`
- Terms: Valuation
- Classes: none
- Functions: _source, test_streamlit_has_only_four_canonical_primary_surfaces, test_active_streamlit_surface_has_no_legacy_decision_authority, test_active_api_registers_cio_and_not_personal_authority, test_canonical_cycle_enforces_all_four_governing_stages, test_active_entrypoints_do_not_import_weighted_committee_authority, test_public_contracts_repeat_the_governing_rule_and_boundaries

## `tests/test_canonical_production_context_adapter.py`
- Terms: ProductionCandidateEvidence
- Classes: none
- Functions: _lineage, _candidate_evidence, _context_snapshot, _persist_universe, _persist_screening, _adapter, test_persisted_certified_authorities_complete_the_full_cio_path, test_screening_publication_after_decision_blocks_execution, test_runtime_ranking_drift_blocks_the_cio_cycle

## `tests/test_cio_persistence.py`
- Terms: LivingThesis
- Classes: none
- Functions: _workflow, _journal, test_complete_cio_workflow_is_hash_chained_and_replayable, test_exact_candidate_append_is_idempotent, test_event_identifier_cannot_be_reused_for_different_content, test_database_triggers_block_update_and_delete, test_hash_verification_detects_out_of_band_tampering, test_candidate_serializer_preserves_quantitative_lineage, test_specialist_and_decision_serializers_preserve_authority_and_dissent, test_event_payload_is_canonical_json, test_event_filters_return_only_requested_type

## `tests/test_cross_asset_forecast_specialist.py`
- Terms: CandidateDecisionRecord
- Classes: none
- Functions: _candidate, _forecast, _context, test_forecast_specialist_is_separate_and_makes_a_calibrated_recommendation, test_forecast_specialist_abstains_when_calibration_is_not_good_enough, test_missing_forecast_packet_abstains_without_blocking_other_specialists

## `tests/test_cross_currency_portfolio_state.py`
- Terms: Valuation
- Classes: none
- Functions: test_legacy_usd_snapshot_round_trips_without_fx_configuration, test_global_equity_preserves_local_and_base_currency_values, test_non_base_currency_cash_is_translated_once, test_non_base_position_requires_fx_lineage_and_base_acquisition_cost, test_future_known_fx_and_base_cash_duplication_are_rejected, test_position_identity_prevents_symbol_collision_across_venues, test_cross_currency_implementation_event_preserves_base_amounts, test_cross_currency_snapshot_remains_append_only

## `tests/test_decision_continuity_governance.py`
- Terms: Valuation, LivingThesis
- Classes: none
- Functions: _performance, test_champion_challenger_requires_governed_independent_promotion, test_governed_scenario_authority_requires_complete_requested_coverage, test_structured_thesis_scoring_rewards_testable_fail_closed_conditions, test_derivative_allocation_requires_complete_lifecycle_profile, test_emergency_derisking_relaxes_soft_turnover_and_reports_residuals, test_production_state_can_be_reconstructed_by_instrument_across_candidate_ids, test_calibration_treats_correct_abstention_as_success, test_point_in_time_evaluation_reports_continuous_distribution_score

## `tests/test_decision_discipline.py`
- Terms: Valuation
- Classes: none
- Functions: invalidation_trigger, test_thesis_lifecycle_preserves_append_only_transitions, test_closed_thesis_cannot_be_reactivated, test_numeric_trigger_requires_threshold, test_evidence_trust_score_is_explicit_and_explainable, test_cross_asset_map_preserves_direction_and_lag, test_scenario_requires_explicit_shocks_and_assumptions, material_dissent, test_dissent_register_preserves_material_minority_view, test_resolved_dissent_is_not_reported_as_open, test_no_action_is_formal_terminal_committee_outcome

## `tests/test_decision_process_upgrade.py`
- Terms: Valuation
- Classes: none
- Functions: test_cio_uses_true_best_alternative_and_records_handoff, test_scenario_reconciliation_preserves_bear_probability_and_path_risk, test_dependency_graph_discounts_sources_with_shared_upstream_origin, test_forecast_abstention_lowers_coverage_without_creating_dissent, test_hysteresis_defers_first_buy_but_emergency_reduction_bypasses, test_asset_class_and_horizon_matrix_is_stricter_for_tactical_crypto, test_real_ranking_inputs_affect_portfolio_component, test_inaction_is_scored_as_missed_opportunity_or_avoided_loss, test_joint_scenario_controls_remove_tail_worsening_allocation, test_multi_start_portfolio_search_selects_superior_candidate

## `tests/test_decision_quality.py`
- Terms: Valuation
- Classes: none
- Functions: test_decision_quality_does_not_conflate_luck_and_process

## `tests/test_decision_quality_reconciliation.py`
- Terms: CandidateDecisionRecord, AssetSpecificEvidencePacket, Valuation
- Classes: none
- Functions: _candidate, _context, _analysis, _packet, test_current_holding_always_enters_mandatory_review_lane, test_candidate_supplied_portfolio_contribution_has_no_screening_authority, test_reconciliation_derives_probability_from_adjusted_distribution, test_duplicate_evidence_origins_reduce_specialist_adjustments, test_specialist_evidence_already_used_by_baseline_is_discounted, test_options_require_and_preserve_nonlinear_payoff_distribution, test_asset_metrics_expose_units_direction_and_horizon, _learning_observation, test_learning_reports_keep_asset_horizon_and_regime_segments_separate, test_forecast_specialist_adjustment_is_conservatively_capped

## `tests/test_decision_replay.py`
- Terms: Valuation
- Classes: none
- Functions: _replay, test_replay_preserves_the_full_reasoning_chain, test_replay_schema_labels_hindsight_separately

## `tests/test_documentation_authority.py`
- Terms: Valuation
- Classes: none
- Functions: _read, test_active_documentation_has_one_compounding_mandate, test_operational_constraints_are_not_competing_objectives, test_active_alert_docs_use_only_canonical_topics, test_retired_database_is_migration_only, test_documentation_preserves_truthful_readiness_boundary

## `tests/test_forecast_evidence.py`
- Terms: CandidateForecastSupport
- Classes: _Context, _Delegate
- Functions: _forecast, test_forecast_preserves_required_governance_lineage, test_forecast_probabilities_and_supporting_only_boundary_fail_closed, test_future_known_forecast_cannot_support_a_decision, test_forecast_and_candidate_reference_stores_are_append_only, _manifest, test_forecast_reference_cannot_name_an_unqualified_candidate, _cycle_context, _translated_support, test_forecast_provider_attaches_separated_specialist_context, test_forecast_specialist_translation_requires_complete_scenario_coverage

## `tests/test_full_universe_screening.py`
- Terms: CandidateDecisionRecord
- Classes: Clock, ActiveCatalogService, MetricsProvider, CandidateProvider
- Functions: _coverage, _catalog, _metrics, _context, _request, _candidate, _orchestrator, test_complete_cycle_publishes_only_after_every_constituent, test_partition_retry_is_recorded_and_succeeds, test_failed_cycle_never_publishes_or_reaches_cio_journal, test_rerun_resumes_prior_results_without_rescreening_them, test_persisted_publication_replays_without_active_provider_and_repairs_journal, test_missing_metrics_fail_closed_before_publication, test_missing_certified_active_catalog_fails_closed, test_screening_history_is_append_only_and_tamper_evident

## `tests/test_governed_historical_learning.py`
- Terms: CandidateDecisionRecord, HistoricalLearning
- Classes: none
- Functions: _candidate, _manifest, test_resolver_attaches_restrictive_outcome_and_regime_context, test_future_manifest_is_rejected, test_historical_learning_cannot_grant_positive_authority, test_live_cycle_committee_and_cio_apply_historical_controls

## `tests/test_horizon_aligned_historical_learning.py`
- Terms: HistoricalLearning
- Classes: none
- Functions: test_live_calibration_bounds_extreme_regret_but_preserves_raw_value, test_live_resolver_discloses_bounded_regret_and_policy_exclusions, test_live_resolver_rejects_macro_incomplete_sidecar

## `tests/test_intelligence_investment_committee.py`
- Terms: Valuation
- Classes: none
- Functions: make_recommendation, test_default_committee_evaluates_all_roles, test_evaluation_is_deterministic

## `tests/test_investment_committee.py`
- Terms: Valuation
- Classes: MockEconomist, MockRiskOfficer
- Functions: test_committee_collects_one_opinion_per_member, test_committee_conducts_meeting

## `tests/test_market_breadth_engine.py`
- Terms: PriceBar
- Classes: FakeMarketBreadthProvider
- Functions: _bars, test_complete_fixture_reports_broadening_market_participation, test_narrow_leadership_cannot_be_called_healthy_breadth, test_broad_breakdown_reports_stressed_breadth, test_partial_constituent_failure_reduces_coverage_without_imputation, test_stale_constituent_evidence_is_disclosed, test_unconfigured_provider_returns_explicit_unavailable_result, test_configured_builder_is_unavailable_without_a_source, test_json_provider_filters_future_members_and_fingerprints_source

## `tests/test_market_data_contract.py`
- Terms: PriceBar, MarketDataProvider
- Classes: FixtureMarketProvider
- Functions: provenance, test_equity_quote_and_bar_preserve_venue_and_time, test_crypto_derivatives_are_venue_specific, test_batch_enforces_point_in_time_boundary, test_batch_rejects_cross_venue_conflation, test_bar_query_requires_interval, test_price_bar_rejects_invalid_ohlc_relationship, test_announced_corporate_action_may_be_effective_later, test_provider_protocol_is_runtime_checkable

## `tests/test_multi_asset_evidence.py`
- Terms: AssetSpecificEvidencePacket, Valuation
- Classes: none
- Functions: _observations, _metrics, _packet, test_each_expanded_market_requires_a_complete_asset_packet, test_repeated_vendor_delivery_counts_as_one_originating_fact, test_missing_asset_specific_metric_fails_closed, test_future_known_or_stale_asset_evidence_is_rejected, test_packet_must_match_the_screened_candidate_and_cutoff, test_asset_evidence_store_is_exact_idempotent_and_append_only

## `tests/test_multi_asset_governance.py`
- Terms: Valuation
- Classes: none
- Functions: _candidate, _complete_profile, _approval, test_expansion_markets_remain_intelligence_only_without_approval, test_complete_active_approval_allows_paper_recommendation_scope, test_research_approval_cannot_authorize_portfolio_action, test_paper_approval_requires_every_asset_specific_capability, test_asset_specific_session_and_custody_models_are_enforced, test_expired_or_wrong_venue_approval_fails_closed, test_suspension_supersedes_prior_paper_approval, test_core_us_universe_behavior_does_not_require_expansion_approval, test_asset_class_approval_history_is_append_only

## `tests/test_multi_asset_thesis_evaluation.py`
- Terms: Valuation
- Classes: none
- Functions: _global_observation, _alternative_returns, test_global_return_decomposes_local_currency_interaction_and_cost, test_base_currency_crypto_has_no_currency_or_interaction_return, test_non_base_observation_requires_complete_fx_lineage_and_no_hindsight, test_multi_asset_evaluator_preserves_core_process_and_alternative_authority, test_multi_asset_performance_feeds_existing_living_thesis_monitor, test_currency_driven_loss_remains_visible_when_local_asset_is_positive, test_multi_asset_evaluation_history_is_idempotent_append_only_and_tamper_evident

## `tests/test_multi_asset_universe.py`
- Terms: Valuation
- Classes: none
- Functions: _coverage, _instrument_record, _listing, _metric, _profile, _approve, _snapshot, test_multi_asset_builder_excludes_every_unapproved_market, test_multi_asset_builder_preserves_approval_lineage_for_all_markets

## `tests/test_multi_engine_governance.py`
- Terms: Valuation
- Classes: none
- Functions: _assessment, _bundle, _synthesis, test_default_policy_is_versioned_and_non_transactional, test_cleared_governance_preserves_scores_and_has_no_authority, test_partial_noncritical_evidence_caps_confidence, test_missing_critical_engine_blocks_high_conviction_positive, test_aggregate_and_engine_disagreement_is_conflicted, test_credit_veto_blocks_conviction_but_does_not_direct_a_sale, test_risk_veto_requires_confident_current_evidence, test_stale_critical_engine_applies_stricter_confidence_ceiling, test_insufficient_synthesis_makes_decision_unavailable, test_policy_rejects_hard_minimum_above_warning_minimum, test_store_is_append_only_and_retry_idempotent

## `tests/test_multi_engine_normalization.py`
- Terms: AnalyticalEngineResult
- Classes: none
- Functions: _evidence, _result, _all_results, test_normalization_produces_seven_assessments_without_aggregation, test_every_engine_has_an_explicit_semantic_policy, test_source_score_is_not_blindly_copied, test_custom_lower_is_supportive_policy_is_inverted_explicitly, test_missing_engine_is_explicitly_unavailable_without_imputation, test_explicit_unavailable_result_remains_unscored, test_data_quality_and_confidence_penalize_stale_fallback_evidence, test_supporting_and_contradictory_evidence_are_retained, test_future_engine_result_is_rejected, test_unknown_and_duplicate_engines_are_rejected, test_normalization_store_is_idempotent_and_append_only, test_store_rejects_different_content_for_same_timestamp, test_read_only_store_handles_pre_normalization_database

## `tests/test_multi_engine_synthesis_weights.py`
- Terms: Valuation
- Classes: none
- Functions: _assessment, _bundle, test_default_policy_has_fixed_complete_weights, test_complete_synthesis_produces_separate_scores_without_authority, test_partial_synthesis_discloses_unallocated_weight, test_below_threshold_is_insufficient_and_publishes_no_scores, test_policy_rejects_weight_totals_that_do_not_equal_one, test_store_is_append_only_and_retry_idempotent

## `tests/test_operational_slos.py`
- Terms: Valuation
- Classes: none
- Functions: _provider, _cycle, _by_name, test_policy_uses_latest_weekday_schedule_in_configured_timezone, test_cycle_is_pending_before_deadline_and_breached_after_deadline, test_complete_cycle_requires_active_catalog_full_coverage_and_deadline, test_provider_staleness_and_integrity_fail_closed, test_thesis_and_evaluation_deadlines_use_frozen_journal_records, test_decision_evaluation_deadline_is_inclusive_and_breaches_afterward, test_missing_or_invalid_journal_blocks_journal_slos, test_slo_store_is_append_only_idempotent_and_tamper_evident, test_source_marks_missing_authoritative_stores_as_blocking, test_snapshot_publishes_prometheus_objective_metrics

## `tests/test_opportunity_engine.py`
- Terms: CandidateDecisionRecord
- Classes: none
- Functions: _instrument, _candidate, _context, test_qualified_candidate_reaches_committee_queue, test_unsupported_asset_never_reaches_committee, test_weak_stale_illiquid_or_incomplete_candidate_is_rejected, test_context_recalculates_opportunity_cost_against_current_holding, test_each_declared_qualification_hurdle_has_screening_authority, test_stale_recorded_opportunity_cost_is_rejected, test_ranker_prefers_stronger_total_capital_allocation_quality, test_ranking_is_fully_disclosed_and_reconciles_to_score, test_empty_candidate_set_produces_explicit_empty_queue, test_candidate_ids_and_instruments_must_be_unique, test_candidate_and_opportunity_set_must_share_decision_time

## `tests/test_paper_operation_evidence.py`
- Terms: Valuation
- Classes: none
- Functions: _observation, _policy, test_complete_control_sample_is_ready_only_for_governance_review, test_small_clean_sample_is_insufficient_not_blocked, test_operational_and_integrity_failures_block_review, test_underperforming_portfolio_is_diagnostic_not_automatic_blocker, test_alert_false_positive_rate_blocks_only_after_minimum_feedback_sample, test_observation_periods_cannot_overlap_or_use_future_knowledge, test_store_is_idempotent_append_only_and_tamper_evident

## `tests/test_paper_trading_launch.py`
- Terms: Valuation
- Classes: none
- Functions: _evidence, test_policy_and_example_evidence_match_schema, test_complete_immediate_evidence_is_ready_but_paper_only, test_any_operating_or_portfolio_failure_blocks_launch, test_latest_blocked_assessment_supersedes_prior_ready_report, test_launch_and_runtime_control_stores_are_append_only, test_operational_launch_helper_requires_active_runtime_switch, test_expiry_and_version_mismatch_fail_closed, test_launch_cli_persists_credential_safe_report

## `tests/test_personal_cio_api.py`
- Terms: Valuation
- Classes: none
- Functions: _briefing, _client, test_latest_cio_briefing_is_the_primary_read_surface, test_cio_history_and_supporting_audit_surfaces_are_read_only, test_process_endpoint_states_the_complete_governing_loop, test_personal_cio_conviction_and_investor_memory_routes_are_isolated

## `tests/test_point_in_time_evaluation.py`
- Terms: Valuation
- Classes: none
- Functions: _cycle, _realized, test_cycle_journals_construction_and_complete_evidence_snapshot, test_snapshot_rejects_evidence_unavailable_at_decision_time, test_evaluator_requires_exact_original_capital_alternative_set, test_evaluation_reconciles_selection_sizing_timing_and_cost, test_disciplined_process_can_have_negative_outcome, test_confidence_calibration_uses_frozen_decision_confidence, test_walk_forward_audit_blocks_lookahead_and_survivorship_bias, test_valid_walk_forward_and_paper_fill_are_append_only

## `tests/test_point_in_time_security_master.py`
- Terms: Valuation
- Classes: none
- Functions: authoritative_coverage, partial_coverage, _issuer, _instrument, catalog, metrics, test_symbol_and_venue_history_resolve_at_each_decision_boundary, test_knowledge_cutoff_preserves_later_corrections_without_rewriting_history, test_delisted_security_remains_in_historical_universe_but_not_future_snapshot, test_version1_builder_creates_reproducible_structural_memberships, test_builder_excludes_missing_or_stale_dynamic_qualification_data, test_partial_coverage_cannot_be_mislabeled_authoritative, test_market_metrics_reject_lookahead_availability, test_catalog_serialization_round_trip_preserves_temporal_identity, test_sqlite_store_is_idempotent_hash_chained_and_append_only, test_integrity_verification_detects_out_of_band_tampering, test_candidate_instrument_requires_security_master_lineage, test_membership_interval_rejects_invalid_boundaries

## `tests/test_portfolio_integrity_specialist.py`
- Terms: Valuation
- Classes: none
- Functions: _snapshot, _buy_fill, _buy_event, test_specialist_certifies_reconciled_buy, test_specialist_holds_cash_mismatch, test_specialist_holds_share_mismatch, test_integrity_specialist_is_not_a_committee_investment_vote

## `tests/test_product_test_readiness.py`
- Terms: Valuation
- Classes: none
- Functions: _evidence, test_ready_diagnostics_do_not_require_launch_clearance, test_missing_launch_and_resilience_campaign_do_not_block_diagnostic_readiness, test_missing_market_and_data_authorities_remains_development_in_progress, test_closed_development_with_failed_technical_gate_is_blocked, test_integrity_or_incident_failures_block_readiness, test_readiness_history_is_append_only_and_tamper_evident

## `tests/test_production_canonical_scheduler.py`
- Terms: CandidateDecisionRecord, Valuation
- Classes: CapturingCycle, ContextProvider
- Functions: _candidate, _opportunity, _portfolio, _publication, _context, _store, test_executor_uses_only_candidates_from_complete_publication, test_executor_fails_closed_without_persisted_publication, test_executor_rejects_context_timestamp_mismatch, test_worker_claims_one_canonical_cycle_and_replays_idempotently, test_active_scheduler_source_has_no_legacy_decision_pipeline

## `tests/test_production_context_assembly.py`
- Terms: CandidateDecisionRecord, ProductionCandidateEvidence, Valuation
- Classes: none
- Functions: _candidate, _screening_context, _approved_lineage, _candidate_evidence, _persist_screening, _persist_portfolio, _context_snapshot, _provider, test_persisted_authorities_complete_a_journaled_cio_cycle, test_provider_rejects_missing_qualified_candidate_coverage, test_stale_evidence_is_rejected_before_context_persistence, test_candidate_is_compared_with_other_alternatives_not_itself

## `tests/test_production_data_enablement.py`
- Terms: Valuation
- Classes: none
- Functions: _capability, test_all_required_sources_enable_authoritative_decisions, test_missing_engine_keeps_production_data_partial, test_deficient_provider_discloses_exact_gaps, test_duplicate_and_unknown_engines_are_rejected

## `tests/test_release_authority_isolation.py`
- Terms: Valuation
- Classes: none
- Functions: test_active_release_and_deployment_surfaces_exclude_retired_entrypoints, test_active_release_surface_names_only_canonical_decision_path

## `tests/test_risk_integration.py`
- Terms: TechnicalMomentum, Valuation
- Classes: _CanonicalExecutor
- Functions: test_multi_engine_cycle_persists_seven_results_without_changing_contract, test_personal_cio_adds_risk_context_without_changing_action, test_risk_api_is_read_only_and_returns_latest_result

## `tests/test_robust_decision_framework.py`
- Terms: CandidateDecisionRecord, Valuation
- Classes: none
- Functions: _candidate, _context, test_robust_candidate_clears_geometric_and_stress_controls, test_inconsistent_success_probability_is_rejected_even_with_high_arithmetic_return, test_malformed_scenario_order_is_fail_closed, test_short_horizon_returns_are_compared_on_an_annualized_geometric_basis, test_robustness_is_enforced_at_the_actual_target_weight, _observation, test_decision_learning_requires_sufficient_out_of_sample_breadth, test_positive_calibrated_outcomes_become_eligible_only_for_human_review, test_material_negative_value_added_suspends_model_version, test_learning_report_cannot_mix_model_versions

## `tests/test_run_paper_execution.py`
- Terms: Valuation
- Classes: none
- Functions: _files, test_cli_executes_complete_paper_batch, test_cli_require_complete_fails_for_closed_market, test_cli_rejects_naive_execution_timestamp

## `tests/test_run_paper_operation_review.py`
- Terms: Valuation
- Classes: none
- Functions: _payload, test_cli_records_observations_and_report_without_live_authority, test_cli_fails_closed_when_evidence_is_not_ready

## `tests/test_run_slos.py`
- Terms: Valuation
- Classes: none
- Functions: test_run_slos_reports_blocked_state_without_creating_authority, test_run_slos_records_terminal_cycle_and_assessment

## `tests/test_run_thesis_monitoring.py`
- Terms: LivingThesis
- Classes: Provider
- Functions: _module, test_cli_runs_due_scheduled_review, test_cli_event_file_fails_missing_thesis_with_nonzero_required_status, test_cli_rejects_invalid_factory

## `tests/test_stage_binding_approval.py`
- Terms: Valuation
- Classes: none
- Functions: _bindings, _approval, test_exact_active_approval_and_required_secret_allow_validation, test_altered_binding_hash_fails_closed, test_missing_secret_or_version_mismatch_blocks, test_latest_suspension_or_expiry_supersedes_prior_approval, test_secret_values_and_unapproved_modules_are_prohibited, test_stage_binding_approval_history_is_append_only

## `tests/test_technical_momentum_engine.py`
- Terms: TechnicalMomentum, PriceBar
- Classes: FakeTechnicalMomentumProvider
- Functions: _bars, test_broad_multi_horizon_support_reports_expanding, test_confirmed_breakdown_reports_stressed, test_short_term_rebound_cannot_be_called_healthy_trend, test_mixed_evidence_remains_neutral, test_partial_history_reduces_coverage_without_imputation, test_elevated_realized_volatility_is_disclosed, test_stale_price_history_is_disclosed, test_unconfigured_provider_returns_explicit_unavailable_result, test_configured_builder_is_unavailable_without_source, test_json_provider_excludes_future_bars_and_fingerprints_source

## `tests/test_technical_momentum_integration.py`
- Terms: TechnicalMomentum, Valuation
- Classes: _CanonicalExecutor
- Functions: test_multi_engine_cycle_persists_six_results_without_changing_contract, test_personal_cio_adds_technical_context_without_changing_action, test_technical_momentum_api_is_read_only_and_returns_latest_result

## `tests/test_thesis_monitoring.py`
- Terms: LivingThesis
- Classes: none
- Functions: _thesis, _update, test_approved_decision_creates_active_living_thesis, test_stable_update_continues_monitoring_without_cio_action_proposal, test_strengthening_thesis_proposes_cio_increase_review, test_weakening_thesis_proposes_cio_reduce_review, test_stale_evidence_forces_evidence_review, test_materially_superior_replacement_proposes_reduce_or_exit, test_explicit_invalidation_has_priority_over_other_changes, test_applying_review_preserves_original_thesis_and_appends_state, test_terminal_thesis_cannot_be_reviewed_again, test_monitoring_proposals_are_not_final_cio_actions, test_review_must_match_current_thesis_snapshot

## `tests/test_thesis_monitoring_orchestration.py`
- Terms: LivingThesis
- Classes: EvidenceProvider, Publisher
- Functions: _journal, _orchestrator, test_scheduled_stable_review_updates_snapshot_without_alert, test_invalidation_queues_urgent_cio_review_and_notifies, test_event_trigger_runs_before_scheduled_deadline, test_no_due_thesis_and_no_event_produces_no_work, test_duplicate_trigger_replays_without_provider_or_notification_duplication, test_same_evidence_fingerprint_is_suppressed_inside_window, test_provider_failure_isolated_and_writes_no_thesis_review, test_missing_thesis_trigger_fails_cleanly, test_corrupt_journal_blocks_entire_monitoring_cycle, test_monitoring_store_is_append_only_and_tamper_evident

## `tests/test_universal_market_scope.py`
- Terms: Valuation
- Classes: none
- Functions: _candidate, _profile, _append, test_universal_governed_scope_covers_every_classified_non_core_market, test_every_governed_market_can_enter_direct_recommendation_after_complete_approval, test_every_governed_market_remains_evidence_only_without_active_approval, test_us_listed_wrapper_is_governed_by_underlying_crypto_exposure, test_governance_status_reports_all_active_structure_specific_profiles, test_contract_multiplier_is_preserved_in_canonical_valuation_round_trip, test_universal_execution_policy_has_asset_specific_routes_and_limits

## `tests/test_valuation_engine.py`
- Terms: Valuation
- Classes: FakeValuationProvider
- Functions: _month, _dataset, test_complete_fixture_reports_broad_valuation_support, test_broadly_compressed_yields_report_stretched_valuation, test_mixed_valuation_evidence_remains_neutral, test_one_attractive_multiple_cannot_define_the_market, test_nonpositive_earnings_yield_is_excluded_not_called_cheap, test_missing_metrics_reduce_coverage_without_imputation, test_stale_valuation_evidence_is_disclosed, test_future_observations_are_excluded, test_unconfigured_provider_returns_explicit_unavailable_result, test_configured_builder_is_unavailable_without_source, test_json_provider_filters_future_data_and_fingerprints_source

## `tests/test_valuation_integration.py`
- Terms: Valuation
- Classes: _CanonicalExecutor
- Functions: test_multi_engine_cycle_persists_five_results_without_changing_contract, test_personal_cio_adds_valuation_context_without_changing_action, test_valuation_api_is_read_only_and_returns_latest_result

## `thesis/__init__.py`
- Terms: LivingThesis
- Classes: none
- Functions: none

## `thesis/conditions.py`
- Terms: package inventory
- Classes: ThesisConditionOperator, MissingDataBehavior, ThesisConditionConsequence, ThesisCondition, StructuredThesisQuality, StructuredThesisConditionScorer
- Functions: _text

## `thesis/models.py`
- Terms: CandidateDecisionRecord, LivingThesis
- Classes: ThesisReviewProposal, LivingThesis, ThesisEvidenceUpdate, ThesisReview
- Functions: _required_text, _aware, _finite, _text_tuple

## `thesis/multi_asset.py`
- Terms: Valuation, LivingThesis
- Classes: MultiAssetThesisAssessment, MultiAssetThesisEvidenceAdapter
- Functions: _text, _texts, _number

## `thesis/orchestration.py`
- Terms: LivingThesis
- Classes: ThesisMonitoringError, ThesisMonitoringIntegrityError, ThesisTriggerSource, ThesisReviewPriority, ThesisMonitoringEventType, ThesisMonitoringTrigger, CIOThesisReviewQueueItem, ThesisMonitoringResult, ThesisMonitoringCycleResult, ThesisEvidenceProvider, ThesisNotificationPublisher, ThesisMonitoringOperationalEvent, SQLiteThesisMonitoringStore, ThesisMonitoringOrchestrator
- Functions: _required_text, _aware, _canonical_json, _fingerprint, thesis_from_payload, review_from_payload, _trigger_payload, _queue_priority

## `thesis/service.py`
- Terms: LivingThesis
- Classes: ThesisMonitoringPolicy, ThesisMonitor
- Functions: none

## `tools/summarize_paper_evidence_paths.py`
- Terms: CandidateDecisionRecord, ProductionCandidateEvidence, ProductionHoldingEvidence, AssetSpecificEvidencePacket, CandidateForecastSupport, TechnicalMomentum, Valuation, LivingThesis, HistoricalLearning, PriceBar, MarketDataProvider, AnalyticalEngineResult
- Classes: none
- Functions: defs, main
