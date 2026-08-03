"""Small constructors used by the versioned event-market rule catalog."""
from intelligence.event_market_models import (
    EventMarketDomain, EventMarketState, EventRule, RuleTransmission,
    TransmissionDirection,
)

def tx(target, direction, magnitude, mechanism, horizon="short_to_medium_term"):
    return RuleTransmission(target, direction, magnitude, mechanism, horizon)

def rule(identifier, domain, state, phrases, *, context=(), excluded=(), channels=(), priority=.75, chain, transmissions, alternatives):
    return EventRule(identifier, domain, state, phrases, context, excluded, channels, priority, chain, transmissions, alternatives)

__all__=["EventMarketDomain","EventMarketState","TransmissionDirection","rule","tx"]
