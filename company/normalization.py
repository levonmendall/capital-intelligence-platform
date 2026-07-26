"""Point-in-time SEC company-fact normalization without synthetic values."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from company.models import FinancialHistory, NormalizedAnnualFinancials
from data.filing import CompanyFact


_DURATION_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "Revenues",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
    ),
    "capital_expenditures": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ),
    "diluted_shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ),
}

_INSTANT_TAGS: dict[str, tuple[str, ...]] = {
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
}

_DEBT_TAGS = (
    "LongTermDebtCurrent",
    "LongTermDebtNoncurrent",
    "LongTermDebtAndFinanceLeaseObligationsCurrent",
    "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    "ShortTermBorrowings",
)

_ALLOWED_FORMS = frozenset({"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"})


def _fact_identifier(fact: CompanyFact) -> str:
    return (
        f"sec:{fact.cik}:{fact.accession_number}:{fact.taxonomy}:"
        f"{fact.tag}:{fact.period_end.isoformat()}"
    )


def _fiscal_year(fact: CompanyFact) -> int:
    return fact.fiscal_year or fact.period_end.year


def _is_annual_duration(fact: CompanyFact) -> bool:
    if fact.period_start is None:
        return False
    duration_days = (fact.period_end - fact.period_start).days
    return duration_days >= 300


@dataclass(frozen=True, slots=True)
class CompanyFactNormalizer:
    """Normalize accepted annual XBRL facts into comparable statement periods."""

    version: str = "company-financial-normalization.v1"
    minimum_annual_periods: int = 1

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        if isinstance(self.minimum_annual_periods, bool) or not isinstance(
            self.minimum_annual_periods,
            int,
        ):
            raise TypeError("minimum_annual_periods must be an integer")
        if self.minimum_annual_periods < 1:
            raise ValueError("minimum_annual_periods must be positive")

    def normalize(
        self,
        facts: tuple[CompanyFact, ...],
        *,
        as_of: datetime,
    ) -> FinancialHistory:
        if not isinstance(facts, tuple) or not all(
            isinstance(item, CompanyFact) for item in facts
        ):
            raise TypeError("facts must be a tuple of CompanyFact values")
        if not isinstance(as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        available = tuple(
            fact
            for fact in facts
            if fact.accepted_at <= as_of and fact.form in _ALLOWED_FORMS
        )
        if not available:
            raise ValueError("no accepted annual company facts are available")
        ciks = {fact.cik for fact in available}
        if len(ciks) != 1:
            raise ValueError("facts must belong to exactly one SEC issuer")
        cik = next(iter(ciks))

        by_year: dict[int, list[CompanyFact]] = defaultdict(list)
        for fact in available:
            by_year[_fiscal_year(fact)].append(fact)

        periods: list[NormalizedAnnualFinancials] = []
        for fiscal_year, year_facts in sorted(by_year.items()):
            normalized = self._normalize_year(
                cik=cik,
                fiscal_year=fiscal_year,
                facts=tuple(year_facts),
            )
            if normalized is not None:
                periods.append(normalized)
        if len(periods) < self.minimum_annual_periods:
            raise ValueError(
                "accepted company facts do not provide the required annual periods"
            )
        return FinancialHistory(
            cik=cik,
            as_of=as_of,
            periods=tuple(periods),
            normalization_version=self.version,
        )

    def _normalize_year(
        self,
        *,
        cik: str,
        fiscal_year: int,
        facts: tuple[CompanyFact, ...],
    ) -> NormalizedAnnualFinancials | None:
        duration = tuple(fact for fact in facts if _is_annual_duration(fact))
        instant = tuple(fact for fact in facts if fact.period_start is None)
        selected: dict[str, CompanyFact] = {}
        for metric, tags in _DURATION_TAGS.items():
            fact = self._select_preferred(duration, tags)
            if fact is not None:
                selected[metric] = fact
        for metric, tags in _INSTANT_TAGS.items():
            fact = self._select_preferred(instant, tags)
            if fact is not None:
                selected[metric] = fact
        revenue = selected.get("revenue")
        if revenue is None:
            return None

        debt_facts = self._select_debt_components(instant)
        relevant = tuple(selected.values()) + debt_facts
        period_end = max(fact.period_end for fact in relevant)
        available_at = max(fact.accepted_at for fact in relevant)
        accessions = tuple(
            dict.fromkeys(fact.accession_number for fact in relevant)
        )
        fact_ids = tuple(dict.fromkeys(_fact_identifier(fact) for fact in relevant))
        debt = sum(fact.value for fact in debt_facts) if debt_facts else None

        return NormalizedAnnualFinancials(
            cik=cik,
            fiscal_year=fiscal_year,
            period_end=period_end,
            available_at=available_at,
            accession_numbers=accessions,
            source_fact_identifiers=fact_ids,
            revenue=revenue.value,
            operating_income=self._value(selected.get("operating_income")),
            net_income=self._value(selected.get("net_income")),
            operating_cash_flow=self._value(
                selected.get("operating_cash_flow")
            ),
            capital_expenditures=self._value(
                selected.get("capital_expenditures")
            ),
            assets=self._value(selected.get("assets")),
            liabilities=self._value(selected.get("liabilities")),
            equity=self._value(selected.get("equity")),
            cash=self._value(selected.get("cash")),
            debt=debt,
            current_assets=self._value(selected.get("current_assets")),
            current_liabilities=self._value(
                selected.get("current_liabilities")
            ),
            diluted_shares=self._value(selected.get("diluted_shares")),
        )

    @staticmethod
    def _value(fact: CompanyFact | None) -> float | None:
        return None if fact is None else fact.value

    @staticmethod
    def _select_preferred(
        facts: tuple[CompanyFact, ...],
        preferred_tags: tuple[str, ...],
    ) -> CompanyFact | None:
        for tag in preferred_tags:
            matches = tuple(fact for fact in facts if fact.tag == tag)
            if matches:
                # Latest accepted fact available at the decision boundary wins.
                # This allows an accepted amendment to supersede its original
                # while preserving both raw facts in the source layer.
                return max(
                    matches,
                    key=lambda fact: (
                        fact.accepted_at,
                        fact.filed_at,
                        fact.accession_number,
                    ),
                )
        return None

    @staticmethod
    def _select_debt_components(
        facts: tuple[CompanyFact, ...],
    ) -> tuple[CompanyFact, ...]:
        selected: list[CompanyFact] = []
        for tag in _DEBT_TAGS:
            matches = tuple(fact for fact in facts if fact.tag == tag)
            if matches:
                selected.append(
                    max(
                        matches,
                        key=lambda fact: (
                            fact.accepted_at,
                            fact.filed_at,
                            fact.accession_number,
                        ),
                    )
                )
        return tuple(selected)


__all__ = ["CompanyFactNormalizer"]