"""Make Today event selection and explanations specific to each source record.

The public collector assigns broad source-level impact channels so that downstream
research does not lose potentially relevant dimensions. Those broad channels are
not suitable as investor-facing conclusions for every record from the source. This
presentation adapter derives a conservative event-specific interpretation, removes
routine administrative notices, and withholds a market explanation when the source
text does not establish a defensible investment connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence


_INSTALLED_KEY = "_capital_intelligence_today_event_alignment_installed"
_EVENT_UI: ModuleType | None = None


@dataclass(frozen=True, slots=True)
class EventInterpretation:
    what_happened: str
    why_it_matters: str
    market_reaction: str
    exposure: str
    what_to_watch: str
    channels: tuple[str, ...]
    lesson_title: str
    lesson_copy: str
    priority: float


@dataclass(frozen=True, slots=True)
class AlignedBriefingItem:
    title: str
    summary: str
    why_it_matters: str
    portfolio_lens: str
    affected_investments: str
    what_to_watch: str
    source: str
    source_type: str
    published_at: datetime
    impact_channels: tuple[str, ...]
    lesson_title: str
    lesson_copy: str


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _truncate(value: object, limit: int) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    shortened = text[: max(1, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (shortened or text[: max(1, limit - 1)]) + "…"


def _values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = _clean(value)
        return (text,) if text else ()
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_values(item))
        return tuple(result)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result = []
        for item in value:
            result.extend(_values(item))
        return tuple(result)
    return ()


def _provenance(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("provenance")
    return value if isinstance(value, Mapping) else {}


def _provider(record: Mapping[str, Any]) -> str:
    return _clean(_provenance(record).get("provider")) or "Public source"


def _source_type(record: Mapping[str, Any]) -> str:
    return _clean(_provenance(record).get("source_type")).title() or "Public"


def _record_text(record: Mapping[str, Any]) -> str:
    fields: list[str] = [
        _clean(record.get("topic")),
        _clean(record.get("summary")),
        _provider(record),
    ]
    fields.extend(_values(record.get("entities")))
    fields.extend(_values(record.get("tags")))
    return " ".join(value for value in fields if value).lower()


def _contains(text: str, values: Iterable[str]) -> bool:
    return any(value in text for value in values)


def _is_federal_register(record: Mapping[str, Any]) -> bool:
    provider = _provider(record).lower()
    tags = " ".join(_values(record.get("tags"))).lower()
    return "federal register" in provider or "federal-register" in tags


def _administrative_without_investment_anchor(text: str) -> bool:
    administrative = _contains(
        text,
        (
            "notice of meeting",
            "notice of meetings",
            "advisory committee meeting",
            "sunshine act meeting",
            "closed meeting",
            "renewal of charter",
            "privacy act system of records",
            "information collection request",
        ),
    )
    if not administrative:
        return False
    investment_anchor = _contains(
        text,
        (
            "exchange",
            "securities",
            "commodity",
            "trust shares",
            "exchange-traded",
            "issuer",
            "company",
            " inc.",
            " llc",
            "energy",
            "power plant",
            "nuclear",
            "bank",
            "credit",
            "capital",
            "tariff",
            "trade",
            "merger",
            "acquisition",
            "drug approval",
            "product recall",
            "cyber",
            "sanction",
            "oil",
            "gas",
            "shipping",
            "inflation",
            "employment",
            "interest rate",
            "federal reserve",
            "treasury",
            "license",
            "environmental assessment",
            "financial",
        ),
    )
    return not investment_anchor


def _interpret(record: Mapping[str, Any]) -> EventInterpretation | None:
    text = _record_text(record)
    title = _truncate(record.get("topic"), 150)
    summary = _truncate(record.get("summary"), 300)
    provider = _provider(record).lower()

    if not title or _administrative_without_investment_anchor(text):
        return None

    market_structure = _contains(
        text,
        (
            "cboe",
            "self-regulatory organization",
            "commodity-based trust shares",
            "exchange-traded",
            " exchange",
            "listing rule",
            "listed product",
            " etf",
        ),
    ) and _contains(text, ("rule", "filing", "order", "approval", "proposal"))
    if market_structure:
        what = (
            "The SEC published a filing and accelerated-approval order for a Cboe BZX "
            "rule change governing commodity-based trust shares."
            if "cboe" in text and "commodity-based trust shares" in text
            else f"A market-structure action was published concerning {title}."
        )
        return EventInterpretation(
            what_happened=what,
            why_it_matters=(
                "The action matters if it changes whether or how a specific exchange-traded "
                "product can list. That can affect investor access, trading liquidity, price "
                "discovery, and expectations for similar products."
            ),
            market_reaction=(
                "Any reaction should be concentrated in the affected product, its sponsor, "
                "the exchange, and the underlying asset. Broader markets are unlikely to "
                "respond unless the order materially changes approval expectations for "
                "similar listings or produces meaningful new flows."
            ),
            exposure=(
                "the proposed exchange-traded product, its sponsor, Cboe BZX, and the "
                "underlying commodity or digital asset"
            ),
            what_to_watch=(
                "the final product identity, listing date, sponsor disclosures, trading "
                "spreads, assets gathered, and follow-on SEC decisions"
            ),
            channels=("regulation", "market_structure", "liquidity"),
            lesson_title="Market structure and access",
            lesson_copy=(
                "Exchange rules matter when they change who can access an asset, how it "
                "trades, or how easily liquidity can form. A filing or approval order does "
                "not by itself guarantee investor demand or a durable price effect."
            ),
            priority=0.58,
        )

    energy_project = _contains(
        text,
        (
            "nuclear",
            "energy center",
            "power plant",
            "electric utility",
            "electric generating",
            "power generation",
        ),
    ) and _contains(
        text,
        (
            "environmental assessment",
            "finding of no significant impact",
            "license",
            "permit",
            "regulatory commission",
            "public comment",
        ),
    )
    if energy_project:
        what = (
            "The Nuclear Regulatory Commission published a draft environmental assessment "
            "and proposed no-significant-impact finding for the Duane Arnold Energy Center "
            "and opened the matter for public comment."
            if "duane arnold" in text
            else (summary if summary and summary.lower() != title.lower() else f"A regulatory project review was published concerning {title}.")
        )
        return EventInterpretation(
            what_happened=what,
            why_it_matters=(
                "This is a project- and issuer-specific regulatory step. It matters only if "
                "the review changes licensing timing, compliance costs, operating life, or "
                "expected generation capacity at the facility."
            ),
            market_reaction=(
                "The clearest sensitivity is company- and project-specific. NextEra-related "
                "valuation or regional power expectations would move only if the final "
                "decision changes cost, timing, operating life, or capacity; a draft "
                "assessment alone should have limited broad-market impact."
            ),
            exposure=(
                "NextEra Energy, the Duane Arnold project, regional power markets, and "
                "nuclear-related contractors"
            ),
            what_to_watch=(
                "the final NRC finding, licensing decision, project timetable, revised cost "
                "estimates, and any change in expected generation capacity"
            ),
            channels=("regulation", "operational", "earnings", "supply"),
            lesson_title="Regulatory project risk",
            lesson_copy=(
                "A regulatory milestone affects value only when it changes expected cash "
                "flows, capital requirements, timing, or usable capacity. Routine procedural "
                "progress should not be treated as a broad market signal."
            ),
            priority=0.52,
        )

    monetary = _contains(
        text,
        (
            "federal reserve",
            "fomc",
            "central bank",
            "policy rate",
            "interest rate decision",
            "treasury yield",
            "inflation report",
            "consumer price index",
        ),
    )
    if monetary:
        return EventInterpretation(
            what_happened=summary if summary and summary.lower() != title.lower() else f"A monetary-policy or inflation update was published: {title}.",
            why_it_matters=(
                "The update can change expectations for inflation, policy rates, and the "
                "return investors require from bonds and equities."
            ),
            market_reaction=(
                "Treasury yields, the dollar, rate-sensitive equities, and credit can react "
                "if the information changes the expected path of policy rather than merely "
                "repeating prior guidance."
            ),
            exposure="Treasuries, the U.S. dollar, rate-sensitive equities, credit, and cash",
            what_to_watch="changes in policy-rate expectations, Treasury yields, inflation forecasts, and official guidance",
            channels=("inflation", "discount_rate", "liquidity"),
            lesson_title="Discount-rate transmission",
            lesson_copy=(
                "Rates matter because they change financing costs and the present value of "
                "future cash flows. The market response depends on the surprise relative to "
                "what investors had already priced."
            ),
            priority=0.64,
        )

    economic_release = _contains(
        text,
        (
            "unemployment rate",
            "employment report",
            "nonfarm payroll",
            "gross domestic product",
            " gdp",
            "retail sales",
            "producer price index",
            "consumer spending",
        ),
    )
    if economic_release:
        return EventInterpretation(
            what_happened=summary if summary and summary.lower() != title.lower() else f"A new economic-data release was published: {title}.",
            why_it_matters=(
                "The release can change expectations for economic growth, company revenue, "
                "inflation, and the future path of monetary policy."
            ),
            market_reaction=(
                "Cyclical equities, bonds, the dollar, and credit may react when the result "
                "differs materially from expectations. A result close to consensus should "
                "have a smaller effect."
            ),
            exposure="cyclical equities, Treasuries, the U.S. dollar, and corporate credit",
            what_to_watch="consensus revisions, subsequent data, earnings guidance, and changes in Treasury yields",
            channels=("growth", "earnings", "inflation", "discount_rate"),
            lesson_title="Expectations versus outcomes",
            lesson_copy=(
                "Markets respond primarily to the difference between the release and what "
                "was already expected. A strong number is not automatically bullish if an "
                "even stronger result was priced in."
            ),
            priority=0.60,
        )

    cyber = _contains(text, ("cyberattack", "cyber incident", "ransomware", "data breach", "known exploited vulnerability"))
    if cyber:
        return EventInterpretation(
            what_happened=summary if summary and summary.lower() != title.lower() else f"A cybersecurity development was reported: {title}.",
            why_it_matters=(
                "The event matters when it disrupts operations, creates remediation costs, "
                "exposes customers, or changes the probability of regulatory and legal loss."
            ),
            market_reaction=(
                "Price effects should be concentrated in directly exposed companies and "
                "their suppliers. Broader markets would react only if the incident impairs "
                "critical infrastructure or reveals a systemic vulnerability."
            ),
            exposure="directly affected companies, critical suppliers, insurers, and cybersecurity vendors",
            what_to_watch="service restoration, confirmed scope, customer exposure, remediation cost, and regulatory action",
            channels=("cyber", "operational", "earnings"),
            lesson_title="Operational risk",
            lesson_copy=(
                "Operational incidents affect value through lost revenue, added costs, legal "
                "liability, and higher uncertainty. The affected entity matters more than the "
                "headline category alone."
            ),
            priority=0.54,
        )

    weather_or_disaster = _contains(
        text,
        (
            "hurricane",
            "wildfire",
            "flood warning",
            "severe weather",
            "earthquake",
            "disaster declaration",
            "active fire detection",
        ),
    )
    if weather_or_disaster:
        return EventInterpretation(
            what_happened=summary if summary and summary.lower() != title.lower() else f"A weather or disaster event was reported: {title}.",
            why_it_matters=(
                "The event matters when it interrupts production, transportation, energy, "
                "housing, or insured property in an economically important area."
            ),
            market_reaction=(
                "Reaction should be concentrated in exposed utilities, insurers, transport, "
                "commodities, and local assets. Broad-market effects require evidence of "
                "material capacity loss or prolonged disruption."
            ),
            exposure="locally exposed utilities, insurers, transport networks, commodities, and property",
            what_to_watch="geographic exposure, duration, insured losses, production outages, and restoration progress",
            channels=("climate_weather", "supply", "operational", "commodity"),
            lesson_title="Exposure mapping",
            lesson_copy=(
                "A hazard becomes an investment event only after location, duration, and "
                "economic exposure are mapped. Severity without exposure is not enough to "
                "infer a market effect."
            ),
            priority=0.46,
        )

    geopolitical = _contains(
        text,
        (
            "sanction",
            "armed conflict",
            "military strike",
            "trade restriction",
            "export control",
            "geopolitical",
        ),
    )
    if geopolitical:
        return EventInterpretation(
            what_happened=summary if summary and summary.lower() != title.lower() else f"A geopolitical or sanctions development was reported: {title}.",
            why_it_matters=(
                "The event matters if it changes trade flows, commodity supply, payment "
                "access, operating permissions, or the risk borne by exposed companies."
            ),
            market_reaction=(
                "Currencies, commodities, defense, energy, shipping, and directly exposed "
                "regional assets may react. Broad-market effects depend on escalation and "
                "the scale of economic transmission."
            ),
            exposure="directly exposed regions and companies, energy, commodities, shipping, currencies, and defense",
            what_to_watch="official implementation, exemptions, retaliation, supply disruption, and company disclosures",
            channels=("geopolitical", "regulation", "supply", "currency"),
            lesson_title="Transmission before headline",
            lesson_copy=(
                "Geopolitical news affects investments through specific channels such as "
                "supply, payments, regulation, and risk premiums. The headline alone does "
                "not establish the size or direction of the market effect."
            ),
            priority=0.55,
        )

    corporate_action = _contains(
        text,
        (
            "earnings release",
            "earnings guidance",
            "profit warning",
            "merger agreement",
            "acquisition agreement",
            "bankruptcy filing",
            "share offering",
            "share repurchase",
            "dividend increase",
            "product recall",
            "drug approval",
        ),
    )
    if corporate_action:
        return EventInterpretation(
            what_happened=summary if summary and summary.lower() != title.lower() else f"A company-specific development was reported: {title}.",
            why_it_matters=(
                "The development can change the affected company's expected revenue, cost, "
                "capital structure, competitive position, or probability of loss."
            ),
            market_reaction=(
                "The primary reaction should be in the named company and close peers. Sector "
                "or index effects require evidence that the development changes a broader "
                "industry assumption."
            ),
            exposure="the named company, close competitors, suppliers, customers, and relevant creditors",
            what_to_watch="management detail, financial magnitude, timing, peer read-through, and analyst estimate revisions",
            channels=("earnings", "operational", "credit"),
            lesson_title="Company-specific versus systemic",
            lesson_copy=(
                "A company event should not be generalized to the whole market without a "
                "clear peer, sector, or macro transmission channel."
            ),
            priority=0.56,
        )

    commodity_or_supply = _contains(
        text,
        (
            "oil production",
            "natural gas",
            "inventory report",
            "shipping disruption",
            "supply disruption",
            "pipeline outage",
            "refinery outage",
            "commodity production",
        ),
    )
    if commodity_or_supply:
        return EventInterpretation(
            what_happened=summary if summary and summary.lower() != title.lower() else f"A commodity or supply development was reported: {title}.",
            why_it_matters=(
                "The event matters if it changes available supply, transport capacity, input "
                "costs, or the revenue earned by producers."
            ),
            market_reaction=(
                "The relevant commodity, producers, transport firms, and input-intensive "
                "industries may react. The direction depends on whether the event tightens "
                "or expands supply."
            ),
            exposure="the affected commodity, producers, transport firms, and major industrial consumers",
            what_to_watch="physical inventories, production, transport capacity, spot prices, and company guidance",
            channels=("supply", "commodity", "earnings"),
            lesson_title="Physical-market transmission",
            lesson_copy=(
                "Commodity events affect investments through changes in physical balance and "
                "input costs. Direction cannot be inferred without knowing whether supply "
                "tightened or expanded."
            ),
            priority=0.50,
        )

    regulatory_source = (
        _is_federal_register(record)
        or "securities and exchange commission" in provider
        or _source_type(record).lower() == "regulatory"
    )
    regulatory_action = _contains(
        text,
        (
            "final rule",
            "proposed rule",
            "rule change",
            "approval order",
            "license application",
            "permit decision",
            "tariff",
            "enforcement action",
            "settlement",
            "investigation",
        ),
    )
    if regulatory_source and regulatory_action:
        return EventInterpretation(
            what_happened=summary if summary and summary.lower() != title.lower() else f"A regulatory action was published concerning {title}.",
            why_it_matters=(
                "The action matters only if it changes permitted activity, compliance cost, "
                "timing, or competitive conditions for the named entities or industry."
            ),
            market_reaction=(
                "Reaction should remain concentrated in directly affected entities. A broad "
                "market move would require the action to materially change sector economics, "
                "financing conditions, or available supply."
            ),
            exposure="the named entities, their closest competitors, and the directly regulated industry",
            what_to_watch="the final effective date, scope, affected entities, implementation cost, and legal response",
            channels=("regulation", "operational", "earnings"),
            lesson_title="Regulatory transmission",
            lesson_copy=(
                "A regulatory notice is investable information only when its economic effect "
                "on revenue, cost, timing, competition, or capital is identifiable."
            ),
            priority=0.30,
        )

    # Federal Register catalogs contain many procedurally important records that
    # do not establish an investment consequence. Withhold them rather than apply
    # the source's broad channel taxonomy to every notice.
    if _is_federal_register(record):
        return None

    # Other public records are also withheld when the text does not establish a
    # specific transmission channel. A truthful quiet-day state is preferable to
    # a generic all-markets paragraph.
    return None


def _event_ui_module() -> ModuleType:
    global _EVENT_UI
    if _EVENT_UI is None:
        import educational_market_briefing_ui as event_ui

        _EVENT_UI = event_ui
    return _EVENT_UI


def _tag_set(record: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(value.lower() for value in _values(record.get("tags")))


def _candidate_score(
    event_ui: ModuleType,
    record: Mapping[str, Any],
    interpretation: EventInterpretation,
    *,
    now: datetime,
) -> float:
    transformed = dict(record)
    transformed["impact_channels"] = list(interpretation.channels)
    allowed = frozenset(set(event_ui._MARKET_CHANNELS) | {"market_structure"})
    return float(
        event_ui._record_score(
            transformed,
            now=now,
            allowed_channels=allowed,
        )
    ) + interpretation.priority


def build_today_items(
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    limit: int = 3,
) -> tuple[AlignedBriefingItem, ...]:
    event_ui = _event_ui_module()
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidates: list[
        tuple[float, datetime, str, str, Mapping[str, Any], EventInterpretation]
    ] = []
    seen: set[str] = set()

    for raw in records:
        if not isinstance(raw, Mapping):
            continue
        title = _clean(raw.get("topic"))
        summary = _clean(raw.get("summary"))
        published_at = event_ui._record_time(raw)
        if not title or not summary or published_at is None:
            continue
        if published_at > evaluated_at or evaluated_at - published_at > event_ui._RECENT_WINDOW:
            continue
        if {"fixture", "sanctions-list"} & _tag_set(raw):
            continue
        interpretation = _interpret(raw)
        if interpretation is None:
            continue
        canonical = _clean(raw.get("canonical_event_identifier")).lower()
        key = canonical or " ".join(title.lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        provider = _provider(raw).lower()
        score = _candidate_score(
            event_ui,
            raw,
            interpretation,
            now=evaluated_at,
        )
        candidates.append(
            (score, published_at, provider, key, raw, interpretation)
        )

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected: list[
        tuple[float, datetime, str, str, Mapping[str, Any], EventInterpretation]
    ] = []
    deferred: list[
        tuple[float, datetime, str, str, Mapping[str, Any], EventInterpretation]
    ] = []
    provider_counts: dict[str, int] = {}
    for candidate in candidates:
        provider = candidate[2]
        if provider_counts.get(provider, 0) >= 1:
            deferred.append(candidate)
            continue
        selected.append(candidate)
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for candidate in deferred:
            selected.append(candidate)
            if len(selected) >= limit:
                break

    items: list[AlignedBriefingItem] = []
    for _, published_at, _, _, record, interpretation in selected:
        items.append(
            AlignedBriefingItem(
                title=_truncate(record.get("topic"), 112),
                summary=_truncate(interpretation.what_happened, 300),
                why_it_matters=_truncate(interpretation.why_it_matters, 360),
                portfolio_lens=_truncate(interpretation.market_reaction, 420),
                affected_investments=_truncate(interpretation.exposure, 220),
                what_to_watch=_truncate(interpretation.what_to_watch, 240),
                source=_truncate(_provider(record), 80),
                source_type=_source_type(record),
                published_at=published_at,
                impact_channels=interpretation.channels,
                lesson_title=interpretation.lesson_title,
                lesson_copy=interpretation.lesson_copy,
            )
        )
    return tuple(items)


def _patch_story(story: ModuleType) -> None:
    if getattr(story, _INSTALLED_KEY, False):
        return

    original_lesson = story._lesson
    story._CHANNEL_NAMES["market_structure"] = "Market structure"

    def lesson(item: object) -> tuple[str, str]:
        title = _clean(getattr(item, "lesson_title", ""))
        copy = _clean(getattr(item, "lesson_copy", ""))
        return (title, copy) if title and copy else original_lesson(item)

    def tags(item: object) -> str:
        return "".join(
            f'<span class="ci-tag">{escape(value)}</span>'
            for value in story._channels(item)
        )

    def exposure(item: object) -> str:
        value = _clean(getattr(item, "affected_investments", ""))
        if not value:
            return ""
        return (
            '<div class="ci-copy" style="margin-top:.72rem"><strong>Most directly exposed:</strong> '
            f'{escape(value)}</div>'
        )

    def primary(item: object) -> str:
        why = _clean(getattr(item, "why_it_matters", ""))
        if not why:
            _, why = lesson(item)
        tag_markup = tags(item)
        return (
            '<div class="ci-primary"><div class="ci-meta"><span class="ci-rank">Most material development</span>'
            f'<span>{escape(_clean(getattr(item, "source_type", "Public")))} · '
            f'{escape(_clean(getattr(item, "source", "Public source")))}</span>'
            f'<span>{escape(story._age_label(getattr(item, "published_at", None)))}</span></div>'
            f'<div class="ci-title">{escape(_clean(getattr(item, "title", "Market development")))}</div>'
            '<div class="ci-three"><div class="ci-box"><div class="ci-label">What happened</div>'
            f'<p>{escape(_clean(getattr(item, "summary", "No concise detail is available.")))}</p></div>'
            '<div class="ci-box"><div class="ci-label">Why it matters</div>'
            f'<p>{escape(why)}</p></div><div class="ci-box"><div class="ci-label">How markets may react</div>'
            f'<p>{escape(_clean(getattr(item, "portfolio_lens", "Market effects remain under review.")))}</p></div>'
            f'</div>{exposure(item)}'
            + (f'<div class="ci-tags">{tag_markup}</div>' if tag_markup else "")
            + "</div>"
        )

    def secondary(item: object, rank: int) -> str:
        why = _clean(getattr(item, "why_it_matters", ""))
        if not why:
            _, why = lesson(item)
        tag_markup = tags(item)
        return (
            '<article class="ci-story"><div class="ci-meta">'
            f'<span class="ci-rank">Development {rank:02d}</span>'
            f'<span>{escape(story._age_label(getattr(item, "published_at", None)))}</span></div>'
            f'<h3>{escape(_clean(getattr(item, "title", "Market development")))}</h3>'
            f'<div class="ci-copy"><strong>What happened:</strong> {escape(_clean(getattr(item, "summary", "")))}</div>'
            f'<div class="ci-copy"><strong>Why it matters:</strong> {escape(why)}</div>'
            f'<div class="ci-copy"><strong>How markets may react:</strong> {escape(_clean(getattr(item, "portfolio_lens", "")))}</div>'
            f'{exposure(item)}'
            + (f'<div class="ci-tags">{tag_markup}</div>' if tag_markup else "")
            + "</article>"
        )

    story._lesson = lesson
    story._tags = tags
    story._primary = primary
    story._secondary = secondary
    setattr(story, _INSTALLED_KEY, True)


def install(
    event_ui: ModuleType | None = None,
    operating_ui: ModuleType | None = None,
    story: ModuleType | None = None,
) -> None:
    """Install event-specific selection and presentation in active Today paths."""

    global _EVENT_UI
    if event_ui is None:
        import educational_market_briefing_ui as event_ui_module

        event_ui = event_ui_module
    if operating_ui is None:
        import operating_intelligence_ui as operating_ui_module

        operating_ui = operating_ui_module
    if story is None:
        import environment_story_placement_refinement as story_module

        story = story_module

    _EVENT_UI = event_ui
    event_ui.build_today_items = build_today_items
    operating_ui.build_today_items = build_today_items
    _patch_story(story)


__all__ = [
    "AlignedBriefingItem",
    "EventInterpretation",
    "build_today_items",
    "install",
]
