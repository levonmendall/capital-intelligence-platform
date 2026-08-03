"""Versioned composable rules for recurring major headline families."""
from intelligence.event_market_rules_1 import RULES_PART_1
from intelligence.event_market_rules_2 import RULES_PART_2
from intelligence.event_market_rules_3 import RULES_PART_3

def default_event_rules():
    return RULES_PART_1 + RULES_PART_2 + RULES_PART_3

__all__=["default_event_rules"]
