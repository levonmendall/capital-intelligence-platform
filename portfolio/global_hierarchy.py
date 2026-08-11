"""Hierarchical global leadership map for marginal-capital competition.

The hierarchy is descriptive portfolio context. It aggregates only candidates that
already survived the canonical opportunity queue and only uses explicit instrument,
portfolio-profile, or governed exposure-graph metadata. Missing classifications stay
`unclassified`; labels are never guessed from company names or price action.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, Mapping, Sequence


class HierarchyLevel(str, Enum):
    DOMAIN = "asset_class"
    COUNTRY_CURRENCY = "country_currency"
    SECTOR_THEME = "sector_theme"
    INDUSTRY = "industry"
    INSTRUMENT = "instrument"


def _clean(value: object, fallback: str = "unclassified") -> str:
    if value is None:
        return fallback
    text = str(getattr(value, "value", value)).strip()
    return text if text else fallback


def _score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("hierarchy score must be numeric")
    number = float(value)
    if not isfinite(number):
        raise ValueError("hierarchy score must be finite")
    return round(max(0.0, min(1.0, number)), 8)


def _instrument_field(instrument: object, *names: str) -> str | None:
    for name in names:
        value = getattr(instrument, name, None)
        if value is None:
            continue
        text = _clean(value, "").strip()
        if text:
            return text
    return None


def _graph_labels(graph: object | None, instrument_identifier: str, kinds: set[str]) -> tuple[str, ...]:
    if graph is None:
        return ()
    nodes = {
        str(getattr(item, "identifier")): item
        for item in tuple(getattr(graph, "nodes", ()) or ())
    }
    instrument_nodes = {
        identifier
        for identifier, node in nodes.items()
        if str(getattr(node, "label", "")).strip() == instrument_identifier
        or identifier == instrument_identifier
    }
    labels: list[str] = []
    for edge in tuple(getattr(graph, "edges", ()) or ()):
        source = str(getattr(edge, "source_identifier", ""))
        target = str(getattr(edge, "target_identifier", ""))
        if source in instrument_nodes:
            other = nodes.get(target)
        elif target in instrument_nodes:
            other = nodes.get(source)
        else:
            continue
        if other is None:
            continue
        kind = str(getattr(getattr(other, "kind", None), "value", getattr(other, "kind", "")))
        if kind in kinds:
            label = _clean(getattr(other, "label", None), "")
            if label:
                labels.append(label)
    return tuple(dict.fromkeys(labels))


@dataclass(frozen=True, slots=True)
class HierarchyCandidatePath:
    candidate_identifier: str
    domain: str
    country_currency: str
    sector_theme: str
    industry: str
    instrument: str

    @property
    def labels(self) -> tuple[tuple[HierarchyLevel, str], ...]:
        return (
            (HierarchyLevel.DOMAIN, self.domain),
            (HierarchyLevel.COUNTRY_CURRENCY, self.country_currency),
            (HierarchyLevel.SECTOR_THEME, self.sector_theme),
            (HierarchyLevel.INDUSTRY, self.industry),
            (HierarchyLevel.INSTRUMENT, self.instrument),
        )


@dataclass(frozen=True, slots=True)
class HierarchyLeadershipNode:
    identifier: str
    level: HierarchyLevel
    label: str
    parent_identifier: str | None
    rank_within_parent: int
    score: float
    candidate_count: int
    strongest_candidate_identifier: str
    candidate_identifiers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "level": self.level.value,
            "label": self.label,
            "parent_identifier": self.parent_identifier,
            "rank_within_parent": self.rank_within_parent,
            "score": self.score,
            "candidate_count": self.candidate_count,
            "strongest_candidate_identifier": self.strongest_candidate_identifier,
            "candidate_identifiers": list(self.candidate_identifiers),
        }


@dataclass(frozen=True, slots=True)
class GlobalOpportunityHierarchy:
    nodes: tuple[HierarchyLeadershipNode, ...]
    candidate_paths: tuple[HierarchyCandidatePath, ...]
    candidate_strengths: tuple[tuple[str, float], ...]
    policy_version: str = "global-opportunity-hierarchy.v1"
    authorizes_capital: bool = False

    @property
    def strength_by_candidate(self) -> dict[str, float]:
        return dict(self.candidate_strengths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "nodes": [item.to_dict() for item in self.nodes],
            "candidate_paths": [
                {
                    "candidate_identifier": item.candidate_identifier,
                    "domain": item.domain,
                    "country_currency": item.country_currency,
                    "sector_theme": item.sector_theme,
                    "industry": item.industry,
                    "instrument": item.instrument,
                }
                for item in self.candidate_paths
            ],
            "candidate_strengths": [list(item) for item in self.candidate_strengths],
            "investment_authority": False,
        }


def candidate_hierarchy_path(
    candidate: object,
    *,
    domain: str,
    portfolio: object,
    exposure_graph: object | None = None,
) -> HierarchyCandidatePath:
    identifier = _clean(getattr(candidate, "identifier", None), "")
    if not identifier:
        raise ValueError("candidate identifier cannot be empty")
    instrument = getattr(candidate, "instrument", candidate)
    instrument_identifier = _clean(
        getattr(instrument, "instrument_id", None) or getattr(instrument, "symbol", None),
        identifier,
    )
    symbol = _clean(getattr(instrument, "symbol", None), instrument_identifier).upper()

    graph_country = _graph_labels(exposure_graph, instrument_identifier, {"country"})
    graph_currency = _graph_labels(exposure_graph, instrument_identifier, {"currency"})
    graph_sector = _graph_labels(exposure_graph, instrument_identifier, {"sector"})
    graph_theme = _graph_labels(exposure_graph, instrument_identifier, {"theme"})
    graph_industry = _graph_labels(exposure_graph, instrument_identifier, {"industry"})

    country = (
        graph_country[0]
        if graph_country
        else _instrument_field(instrument, "country_code", "country", "domicile")
        or "global"
    )
    currency = (
        graph_currency[0]
        if graph_currency
        else _instrument_field(instrument, "currency", "currency_code", "quote_currency")
        or "multi_currency"
    )
    country_currency = f"{country.upper()} / {currency.upper()}"

    profile = None
    profile_getter = getattr(portfolio, "profile", None)
    if callable(profile_getter):
        try:
            profile = profile_getter(identifier)
        except (KeyError, ValueError):
            profile = None
    profile_sector = None if profile is None else getattr(profile, "sector", None)
    sector = graph_sector[0] if graph_sector else _clean(profile_sector, "unclassified")
    theme = (
        graph_theme[0]
        if graph_theme
        else _instrument_field(
            instrument,
            "theme",
            "economic_exposure",
            "economic_exposure_name",
        )
        or "unclassified"
    )
    sector_theme = f"{sector} / {theme}"
    industry = (
        graph_industry[0]
        if graph_industry
        else _instrument_field(instrument, "industry", "subindustry")
        or "unclassified"
    )
    return HierarchyCandidatePath(
        candidate_identifier=identifier,
        domain=_clean(domain),
        country_currency=country_currency,
        sector_theme=sector_theme,
        industry=industry,
        instrument=symbol,
    )


def build_global_opportunity_hierarchy(
    *,
    candidates: Sequence[object],
    base_scores: Mapping[str, float],
    domains: Mapping[str, str],
    portfolio: object,
    exposure_graph: object | None = None,
) -> GlobalOpportunityHierarchy:
    """Aggregate candidate leadership from asset class down to instrument."""

    paths = tuple(
        candidate_hierarchy_path(
            candidate,
            domain=domains[str(getattr(candidate, "identifier"))],
            portfolio=portfolio,
            exposure_graph=exposure_graph,
        )
        for candidate in candidates
    )
    score_by_id = {str(key): _score(value) for key, value in base_scores.items()}
    if set(score_by_id) != {item.candidate_identifier for item in paths}:
        raise ValueError("hierarchy scores must cover exactly the reviewed candidates")

    # Aggregate each path prefix. A top candidate matters more than a large set of weak
    # candidates, while breadth still contributes to the group score.
    groups: dict[tuple[HierarchyLevel, str | None, str], list[str]] = {}
    parent_by_key: dict[tuple[HierarchyLevel, str | None, str], str | None] = {}
    parent_id_by_candidate: dict[str, str | None] = {item.candidate_identifier: None for item in paths}
    path_keys_by_candidate: dict[str, list[tuple[HierarchyLevel, str | None, str]]] = {
        item.candidate_identifier: [] for item in paths
    }
    for path in paths:
        parent: str | None = None
        for level, label in path.labels:
            key = (level, parent, label)
            groups.setdefault(key, []).append(path.candidate_identifier)
            parent_by_key[key] = parent
            path_keys_by_candidate[path.candidate_identifier].append(key)
            parent = f"{level.value}:{parent or 'root'}:{label}"

    raw_nodes: list[tuple[tuple[HierarchyLevel, str | None, str], float, tuple[str, ...], str]] = []
    for key, identifiers in groups.items():
        unique = tuple(dict.fromkeys(identifiers))
        ordered = sorted(unique, key=lambda item: (score_by_id[item], item), reverse=True)
        strongest = score_by_id[ordered[0]]
        mean = sum(score_by_id[item] for item in ordered) / len(ordered)
        breadth = sum(score_by_id[item] >= 0.55 for item in ordered) / len(ordered)
        group_score = _score(0.55 * strongest + 0.30 * mean + 0.15 * breadth)
        raw_nodes.append((key, group_score, tuple(ordered), ordered[0]))

    siblings: dict[tuple[HierarchyLevel, str | None], list[tuple]] = {}
    for value in raw_nodes:
        level, parent, _label = value[0]
        siblings.setdefault((level, parent), []).append(value)
    ranks: dict[tuple[HierarchyLevel, str | None, str], int] = {}
    for values in siblings.values():
        values.sort(key=lambda item: (item[1], item[0][2]), reverse=True)
        for rank, value in enumerate(values, start=1):
            ranks[value[0]] = rank

    nodes = tuple(
        HierarchyLeadershipNode(
            identifier=f"{key[0].value}:{key[1] or 'root'}:{key[2]}",
            level=key[0],
            label=key[2],
            parent_identifier=key[1],
            rank_within_parent=ranks[key],
            score=group_score,
            candidate_count=len(identifiers),
            strongest_candidate_identifier=strongest_identifier,
            candidate_identifiers=identifiers,
        )
        for key, group_score, identifiers, strongest_identifier in sorted(
            raw_nodes,
            key=lambda item: (
                list(HierarchyLevel).index(item[0][0]),
                item[0][1] or "",
                ranks[item[0]],
                item[0][2],
            ),
        )
    )
    node_score = {
        (item.level, item.parent_identifier, item.label): item.score for item in nodes
    }
    strengths: list[tuple[str, float]] = []
    for path in paths:
        scores: list[float] = []
        parent = None
        for level, label in path.labels:
            scores.append(node_score[(level, parent, label)])
            parent = f"{level.value}:{parent or 'root'}:{label}"
        # Higher levels matter, but instrument-specific quality retains the largest
        # weight. This prevents a strong sector from rescuing a weak security.
        strength = _score(
            0.12 * scores[0]
            + 0.15 * scores[1]
            + 0.18 * scores[2]
            + 0.20 * scores[3]
            + 0.35 * scores[4]
        )
        strengths.append((path.candidate_identifier, strength))
    return GlobalOpportunityHierarchy(
        nodes=nodes,
        candidate_paths=paths,
        candidate_strengths=tuple(sorted(strengths)),
    )


__all__ = [
    "GlobalOpportunityHierarchy",
    "HierarchyCandidatePath",
    "HierarchyLeadershipNode",
    "HierarchyLevel",
    "build_global_opportunity_hierarchy",
    "candidate_hierarchy_path",
]
