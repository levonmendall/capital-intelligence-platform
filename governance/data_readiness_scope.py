"""All-markets scope and manifest models."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from cio.models import CandidateAssetClass
from governance.data_readiness_core import (DataDomain, MarketDataScopeState, ProviderDataCapability, _bool, _text, _texts)

@dataclass(frozen=True, slots=True)
class DatasetCoverageRequirement:
    """Minimum usable provider coverage for one market data domain."""

    domain: DataDomain
    provider_identifiers: tuple[str, ...]
    minimum_ready_providers: int = 1
    authoritative_required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.domain, DataDomain):
            raise TypeError("domain must be DataDomain")
        object.__setattr__(
            self,
            "provider_identifiers",
            _texts(
                self.provider_identifiers,
                field_name="provider_identifiers",
                minimum=1,
            ),
        )
        if (
            isinstance(self.minimum_ready_providers, bool)
            or not isinstance(self.minimum_ready_providers, int)
        ):
            raise TypeError("minimum_ready_providers must be an int")
        if not 1 <= self.minimum_ready_providers <= len(
            self.provider_identifiers
        ):
            raise ValueError(
                "minimum_ready_providers must be between 1 and the number "
                "of provider identifiers"
            )
        _bool(
            self.authoritative_required,
            field_name="authoritative_required",
        )


@dataclass(frozen=True, slots=True)
class MarketDataScope:
    """Data requirements and permitted use for one candidate asset class."""

    asset_class: CandidateAssetClass
    state: MarketDataScopeState
    requirements: tuple[DatasetCoverageRequirement, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if not isinstance(self.state, MarketDataScopeState):
            raise TypeError("state must be MarketDataScopeState")
        if not isinstance(self.requirements, tuple) or not all(
            isinstance(item, DatasetCoverageRequirement)
            for item in self.requirements
        ):
            raise TypeError(
                "requirements must contain DatasetCoverageRequirement values"
            )
        domains = tuple(item.domain for item in self.requirements)
        if len(domains) != len(set(domains)):
            raise ValueError(
                f"{self.asset_class.value} requirements cannot repeat a domain"
            )
        object.__setattr__(
            self,
            "rationale",
            _text(self.rationale, field_name="rationale"),
        )
        if self.state is MarketDataScopeState.PROHIBITED:
            if self.requirements:
                raise ValueError("prohibited markets cannot declare data requirements")
        elif not self.requirements:
            raise ValueError("non-prohibited markets require dataset coverage")
        if self.state is MarketDataScopeState.PAPER_ELIGIBLE:
            required = {
                DataDomain.SECURITY_MASTER,
                DataDomain.MARKET_PRICES,
                DataDomain.QUOTES_LIQUIDITY,
                DataDomain.MARKET_CALENDARS,
                DataDomain.EXECUTION_INPUTS,
            }
            missing = required - set(domains)
            if missing:
                raise ValueError(
                    f"paper-eligible {self.asset_class.value} is missing "
                    f"required domains: {sorted(item.value for item in missing)}"
                )


@dataclass(frozen=True, slots=True)
class AllMarketsDataManifest:
    """Version-controlled declaration of the complete market data supply chain."""

    identifier: str
    schema_version: str
    reporting_currency: str
    require_complete_candidate_scope: bool
    providers: tuple[ProviderDataCapability, ...]
    markets: tuple[MarketDataScope, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "schema_version"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "reporting_currency",
            _text(
                self.reporting_currency,
                field_name="reporting_currency",
            ).upper(),
        )
        if len(self.reporting_currency) != 3:
            raise ValueError("reporting_currency must be a three-letter code")
        _bool(
            self.require_complete_candidate_scope,
            field_name="require_complete_candidate_scope",
        )
        if not isinstance(self.providers, tuple) or not self.providers:
            raise ValueError("providers must contain at least one capability")
        if not all(
            isinstance(item, ProviderDataCapability) for item in self.providers
        ):
            raise TypeError("providers must contain ProviderDataCapability values")
        provider_ids = tuple(item.identifier for item in self.providers)
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider identifiers cannot contain duplicates")
        if not isinstance(self.markets, tuple) or not self.markets:
            raise ValueError("markets must contain at least one market scope")
        if not all(isinstance(item, MarketDataScope) for item in self.markets):
            raise TypeError("markets must contain MarketDataScope values")
        asset_classes = tuple(item.asset_class for item in self.markets)
        if len(asset_classes) != len(set(asset_classes)):
            raise ValueError("asset classes cannot be repeated")
        if self.require_complete_candidate_scope:
            missing = set(CandidateAssetClass) - set(asset_classes)
            if missing:
                raise ValueError(
                    "complete candidate scope is missing: "
                    f"{sorted(item.value for item in missing)}"
                )
        known = set(provider_ids)
        for market in self.markets:
            for requirement in market.requirements:
                unknown = set(requirement.provider_identifiers) - known
                if unknown:
                    raise ValueError(
                        f"{market.asset_class.value}/{requirement.domain.value} "
                        "references unknown providers: "
                        f"{sorted(unknown)}"
                    )

    @property
    def required_environment_variables(self) -> tuple[str, ...]:
        """Return every declared provider variable name, never its value."""

        return tuple(
            sorted(
                {
                    variable
                    for provider in self.providers
                    for variable in provider.credential_environment_variables
                }
            )
        )


