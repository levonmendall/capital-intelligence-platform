"""External data providers for the Capital Intelligence Platform."""

from providers.environment_aliases import (
    PROVIDER_ENVIRONMENT_ALIASES,
    install_provider_environment_aliases,
    normalize_provider_environment,
    provider_environment_value,
)

# Provider modules and configuration bindings retain their established canonical
# variable contracts. Populate missing canonical values from supported aliases before
# importing those modules, without replacing canonical values or exposing secrets.
install_provider_environment_aliases()

from providers.configured_dataset import (
    ConfiguredDatasetBinding,
    ConfiguredDatasetProvider,
    ConfiguredDatasetProviderError,
    ConfiguredDatasetProviderSettings,
    TransportResponse,
    build_from_environment as build_configured_dataset_provider,
)
from providers.configured_information import (
    ConfiguredDecisionInformationError,
    ConfiguredDecisionInformationProvider,
    build_configured_decision_information_provider,
)
from providers.configured_pipeline import (
    ConfiguredCandidateScreeningProvider,
    ConfiguredPipelineAdapterError,
    ConfiguredSecurityMasterProvider,
    ConfiguredUniverseMetricsProvider,
    build_configured_candidate_screening_provider,
    build_configured_security_master_provider,
    build_configured_universe_metrics_provider,
)
from providers.crypto_venues import (
    CoinbaseExchangeProvider,
    CryptoVenueBinding,
    CryptoVenueBindingRegistry,
    CryptoVenueProviderError,
    KrakenSpotProvider,
    build_coinbase_exchange_provider,
    build_kraken_spot_provider,
    load_crypto_venue_bindings,
)
from providers.databento import (
    DatabentoBindingRegistry,
    DatabentoInstrumentBinding,
    DatabentoProvider,
    DatabentoProviderError,
    DatabentoRetrievalPolicy,
    build_databento_provider,
    load_databento_bindings,
)
from providers.fred import FREDRetrievalPolicy
from providers.fred_cache import (
    FREDCache,
    FREDCacheRecord,
    JsonFREDCache,
    MemoryFREDCache,
    fred_cache_key,
)
from providers.free_connections import (
    FreeProviderConnectionCatalog,
    FreeProviderConnectionError,
    FreeProviderConnectionIntegrityError,
    FreeProviderConnectionReport,
    FreeProviderConnectionState,
    FreeProviderConnectionVerifier,
    FreeProviderDefinition,
    FreeProviderProbeResult,
    SQLiteFreeProviderConnectionStore,
    load_free_provider_catalog,
)
from providers.gleif import (
    GleifEntityRecord,
    GleifProvider,
    GleifProviderError,
)
from providers.openfigi import (
    OpenFigiInstrumentMatch,
    OpenFigiMappingJob,
    OpenFigiMappingResult,
    OpenFigiProvider,
    OpenFigiProviderError,
)
from providers.public_live_information import (
    PublicLiveCoverageReport,
    PublicLiveInformationError,
    PublicLiveInformationProvider,
    PublicLiveSourceCatalog,
    PublicLiveSourceDefinition,
    PublicLiveSourceResult,
    load_public_live_source_catalog,
)
from providers.public_live_information_extended import (
    ImpactfulPublicLiveInformationProvider,
)
from providers.public_live_information_runtime import (
    GovernedPublicLiveInformationProvider,
)
from providers.sec_edgar import (
    SECEdgarProvider,
    SECEdgarProviderError,
)
from providers.supplemental_quotes import (
    SupplementalQuote,
    SupplementalQuoteCrossCheck,
    SupplementalQuoteError,
    SupplementalQuoteProvider,
)

__all__ = [
    "CoinbaseExchangeProvider",
    "ConfiguredCandidateScreeningProvider",
    "ConfiguredDatasetBinding",
    "ConfiguredDatasetProvider",
    "ConfiguredDatasetProviderError",
    "ConfiguredDatasetProviderSettings",
    "ConfiguredDecisionInformationError",
    "ConfiguredDecisionInformationProvider",
    "ConfiguredPipelineAdapterError",
    "ConfiguredSecurityMasterProvider",
    "ConfiguredUniverseMetricsProvider",
    "CryptoVenueBinding",
    "CryptoVenueBindingRegistry",
    "CryptoVenueProviderError",
    "DatabentoBindingRegistry",
    "DatabentoInstrumentBinding",
    "DatabentoProvider",
    "DatabentoProviderError",
    "DatabentoRetrievalPolicy",
    "FREDCache",
    "FREDCacheRecord",
    "FREDRetrievalPolicy",
    "FreeProviderConnectionCatalog",
    "FreeProviderConnectionError",
    "FreeProviderConnectionIntegrityError",
    "FreeProviderConnectionReport",
    "FreeProviderConnectionState",
    "FreeProviderConnectionVerifier",
    "FreeProviderDefinition",
    "FreeProviderProbeResult",
    "GleifEntityRecord",
    "GleifProvider",
    "GleifProviderError",
    "GovernedPublicLiveInformationProvider",
    "ImpactfulPublicLiveInformationProvider",
    "JsonFREDCache",
    "KrakenSpotProvider",
    "MemoryFREDCache",
    "OpenFigiInstrumentMatch",
    "OpenFigiMappingJob",
    "OpenFigiMappingResult",
    "OpenFigiProvider",
    "OpenFigiProviderError",
    "PROVIDER_ENVIRONMENT_ALIASES",
    "PublicLiveCoverageReport",
    "PublicLiveInformationError",
    "PublicLiveInformationProvider",
    "PublicLiveSourceCatalog",
    "PublicLiveSourceDefinition",
    "PublicLiveSourceResult",
    "SECEdgarProvider",
    "SECEdgarProviderError",
    "SQLiteFreeProviderConnectionStore",
    "SupplementalQuote",
    "SupplementalQuoteCrossCheck",
    "SupplementalQuoteError",
    "SupplementalQuoteProvider",
    "TransportResponse",
    "build_coinbase_exchange_provider",
    "build_configured_candidate_screening_provider",
    "build_configured_dataset_provider",
    "build_configured_decision_information_provider",
    "build_configured_security_master_provider",
    "build_configured_universe_metrics_provider",
    "build_databento_provider",
    "build_kraken_spot_provider",
    "fred_cache_key",
    "install_provider_environment_aliases",
    "load_crypto_venue_bindings",
    "load_databento_bindings",
    "load_free_provider_catalog",
    "load_public_live_source_catalog",
    "normalize_provider_environment",
    "provider_environment_value",
]
