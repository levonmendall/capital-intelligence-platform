"""Final execution-boundary enforcement for certified investable scope.

Construction lineage is resolved against the append-only eligible-universe
publication authority. New exposure may only be created in instruments contained
in that exact publication. Existing positions that are no longer eligible may
only be reduced or closed, and only when their canonical instrument identity
matches the construction and execution profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from governance.eligible_universe import (
    CertifiedEligibleUniversePublication,
    EligibleUniverseError,
    SQLiteCertifiedEligibleUniverseStore,
)
from cio import CandidateAssetClass
from governance import (
    EXPANSION_ASSET_CLASSES,
    AssetClassApprovalState,
)
from portfolio.construction_models import (
    PortfolioConstructionResult,
    TradeSide,
)


class ExecutionEligibilityError(RuntimeError):
    """Raised when execution cannot prove instrument eligibility and lineage."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class ExecutionEligibilityEvidence:
    """Immutable evidence resolved from the trusted publication authority."""

    publication_identifier: str
    publication_content_hash: str
    certification_identifier: str
    security_master_catalog_identifier: str
    security_master_snapshot_identifier: str
    policy_version: str
    instrument_results: tuple[tuple[str, str, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "publication_identifier": self.publication_identifier,
            "publication_content_hash": self.publication_content_hash,
            "certification_identifier": self.certification_identifier,
            "security_master_catalog_identifier": (
                self.security_master_catalog_identifier
            ),
            "security_master_snapshot_identifier": (
                self.security_master_snapshot_identifier
            ),
            "policy_version": self.policy_version,
            "instrument_results": [
                {
                    "symbol": symbol,
                    "instrument_identifier": instrument_identifier,
                    "eligibility_result": result,
                }
                for symbol, instrument_identifier, result in self.instrument_results
            ],
        }


class CertifiedExecutionEligibilityAuthority:
    """Resolve and enforce the exact publication used by construction."""

    def __init__(self, store: SQLiteCertifiedEligibleUniverseStore) -> None:
        if not isinstance(store, SQLiteCertifiedEligibleUniverseStore):
            raise TypeError(
                "store must be SQLiteCertifiedEligibleUniverseStore"
            )
        self.store = store

    def authorize(
        self,
        *,
        construction: PortfolioConstructionResult,
        execution_timestamp: datetime,
        owned_instruments: Mapping[str, str | None],
        execution_instruments: Mapping[str, str] | None = None,
        approval_identifiers: Mapping[str, str] | None = None,
        approval_states: Mapping[str, AssetClassApprovalState] | None = None,
        asset_classes: Mapping[str, CandidateAssetClass] | None = None,
    ) -> ExecutionEligibilityEvidence:
        if not isinstance(construction, PortfolioConstructionResult):
            raise TypeError("construction must be PortfolioConstructionResult")
        timestamp = _aware(
            execution_timestamp,
            field_name="execution_timestamp",
        )
        publication_identifier = (
            construction.eligible_universe_publication_identifier
        )
        if publication_identifier is None:
            raise ExecutionEligibilityError(
                "construction is missing certified eligible-universe lineage"
            )
        publication_identifier = _text(
            publication_identifier,
            field_name="eligible_universe_publication_identifier",
        )
        if set(symbol for symbol, _ in construction.instrument_identifiers) != {
            trade.symbol for trade in construction.trades
        }:
            raise ExecutionEligibilityError(
                "construction instrument identities do not exactly match trades"
            )

        try:
            self.store.verify_integrity()
            publication = self.store.publication(publication_identifier)
            if publication is None:
                raise ExecutionEligibilityError(
                    "certified eligible-universe publication is unavailable"
                )
            publication.require_usable(
                decision_timestamp=construction.as_of,
            )
        except EligibleUniverseError as error:
            raise ExecutionEligibilityError(str(error)) from error
        if publication.certification_expires_at < timestamp:
            raise ExecutionEligibilityError(
                f"eligible-universe certification "
                f"{publication.certification_identifier} is expired at execution"
            )
        content_hash = self.store.content_hash(publication_identifier)
        if content_hash is None:
            raise ExecutionEligibilityError(
                "eligible-universe publication content hash is unavailable"
            )

        normalized_owned = {
            _text(symbol, field_name="owned symbol").upper(): (
                None
                if instrument_identifier is None
                else _text(
                    instrument_identifier,
                    field_name="owned instrument_identifier",
                )
            )
            for symbol, instrument_identifier in owned_instruments.items()
        }
        normalized_execution = self._text_mapping(
            execution_instruments,
            field_name="execution instrument",
        )
        normalized_approvals = self._text_mapping(
            approval_identifiers,
            field_name="approval",
        )
        normalized_states = {
            _text(symbol, field_name="approval state symbol").upper(): state
            for symbol, state in (approval_states or {}).items()
        }
        normalized_asset_classes = {
            _text(symbol, field_name="asset class symbol").upper(): asset_class
            for symbol, asset_class in (asset_classes or {}).items()
        }

        eligible = set(publication.eligible_instrument_identifiers)
        results: list[tuple[str, str, str]] = []
        for trade in construction.trades:
            instrument_identifier = construction.instrument_identifier(trade.symbol)
            if instrument_identifier is None:
                raise ExecutionEligibilityError(
                    f"construction is missing instrument identity for {trade.symbol}"
                )
            execution_identifier = normalized_execution.get(trade.symbol)
            if (
                execution_instruments is not None
                and execution_identifier != instrument_identifier
            ):
                raise ExecutionEligibilityError(
                    f"execution profile instrument does not match construction "
                    f"for {trade.symbol}"
                )

            if trade.side is TradeSide.BUY:
                owned_identifier = normalized_owned.get(trade.symbol)
                if (
                    owned_identifier is not None
                    and owned_identifier != instrument_identifier
                ):
                    raise ExecutionEligibilityError(
                        f"owned instrument identity does not match construction for "
                        f"{trade.symbol}"
                    )
                if instrument_identifier not in eligible:
                    raise ExecutionEligibilityError(
                        f"{trade.symbol} is not eligible for new or increased exposure "
                        f"in publication {publication.identifier}"
                    )
                self._require_trusted_expansion_approval(
                    symbol=trade.symbol,
                    instrument_identifier=instrument_identifier,
                    publication=publication,
                    approval_identifiers=normalized_approvals,
                    approval_states=normalized_states,
                    asset_classes=normalized_asset_classes,
                )
                results.append(
                    (trade.symbol, instrument_identifier, "eligible_new_exposure")
                )
                continue

            owned_identifier = normalized_owned.get(trade.symbol)
            if owned_identifier is None:
                raise ExecutionEligibilityError(
                    f"{trade.symbol} cannot be sold without an owned canonical "
                    "instrument identity"
                )
            if owned_identifier != instrument_identifier:
                raise ExecutionEligibilityError(
                    f"owned instrument identity does not match construction for "
                    f"{trade.symbol}"
                )
            result = (
                "eligible_reduction"
                if instrument_identifier in eligible
                else "legacy_exit_only"
            )
            results.append((trade.symbol, instrument_identifier, result))

        return ExecutionEligibilityEvidence(
            publication_identifier=publication.identifier,
            publication_content_hash=content_hash,
            certification_identifier=publication.certification_identifier,
            security_master_catalog_identifier=(
                publication.security_master_catalog_identifier
            ),
            security_master_snapshot_identifier=(
                publication.security_master_snapshot_identifier
            ),
            policy_version=publication.policy_version,
            instrument_results=tuple(results),
        )

    @staticmethod
    def _text_mapping(
        values: Mapping[str, str] | None,
        *,
        field_name: str,
    ) -> dict[str, str]:
        return {
            _text(symbol, field_name=f"{field_name} symbol").upper(): _text(
                value,
                field_name=field_name,
            )
            for symbol, value in (values or {}).items()
        }

    @staticmethod
    def _require_trusted_expansion_approval(
        *,
        symbol: str,
        instrument_identifier: str,
        publication: CertifiedEligibleUniversePublication,
        approval_identifiers: Mapping[str, str],
        approval_states: Mapping[str, AssetClassApprovalState],
        asset_classes: Mapping[str, CandidateAssetClass],
    ) -> None:
        asset_class = asset_classes.get(symbol)
        if asset_class not in EXPANSION_ASSET_CLASSES:
            return
        expected_approval = publication.approval_identifier_for(
            instrument_identifier
        )
        if expected_approval is None:
            raise ExecutionEligibilityError(
                f"{symbol} is missing trusted asset-class approval lineage in "
                f"publication {publication.identifier}"
            )
        if approval_identifiers.get(symbol) != expected_approval:
            raise ExecutionEligibilityError(
                f"{symbol} execution approval does not match the certified "
                "eligible-universe publication"
            )
        if approval_states.get(symbol) is not AssetClassApprovalState.PAPER_ELIGIBLE:
            raise ExecutionEligibilityError(
                f"{symbol} asset-class approval is not paper_eligible"
            )


__all__ = [
    "CertifiedExecutionEligibilityAuthority",
    "ExecutionEligibilityError",
    "ExecutionEligibilityEvidence",
]
