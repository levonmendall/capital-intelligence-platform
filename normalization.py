from __future__ import annotations
import math

def clamp(value: float, low: float=0, high: float=100) -> float:
    return max(low, min(high, float(value)))

def linear(value: float, low: float, high: float, invert: bool=False) -> float:
    if high <= low: raise ValueError("high must exceed low")
    score=100*(float(value)-low)/(high-low)
    score=clamp(score)
    return 100-score if invert else score

def percentile_rank(value: float, history: list[float], invert: bool=False) -> float:
    if not history: return 50.0
    less=sum(1 for x in history if x < value); equal=sum(1 for x in history if x == value)
    score=100*(less+0.5*equal)/len(history)
    return 100-score if invert else score

def zscore_to_100(z: float, invert: bool=False) -> float:
    score=100/(1+math.exp(-float(z)))
    return 100-score if invert else score

def completeness(signals: dict[str,float], required: set[str]) -> float:
    return len(required.intersection(signals))/len(required) if required else 1.0
