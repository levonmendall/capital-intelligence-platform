from __future__ import annotations
from dataclasses import dataclass
from .models import MarketSnapshot, Evidence, CouncilOpinion
from .normalization import completeness

@dataclass(frozen=True)
class SignalSpec:
    name:str; weight:float; positive:bool=True

class Specialist:
    specialist_id="specialist"; specialist_name="Specialist"; specs:tuple[SignalSpec,...]=()
    def evaluate(self, snapshot: MarketSnapshot)->CouncilOpinion:
        contributions=[]; evidence=[]; present=set(snapshot.signals)
        for spec in self.specs:
            value=float(snapshot.signals.get(spec.name,50)); directional=(value-50) if spec.positive else (50-value)
            contribution=directional*spec.weight
            contributions.append(contribution)
            label="supportive" if directional>5 else "adverse" if directional<-5 else "neutral"
            evidence.append(Evidence(spec.name,value,label,contribution))
        score=max(0,min(100,50+sum(contributions)))
        complete=completeness(snapshot.signals,{x.name for x in self.specs})
        conviction=abs(score-50)/50
        confidence=max(.45,min(.95,.55+.25*complete+.15*conviction))
        recommendation="Overweight risk" if score>=62 else "Underweight risk" if score<=38 else "Neutral"
        flags=tuple(f"Missing signal: {x.name}" for x in self.specs if x.name not in present)
        return CouncilOpinion(self.specialist_id,self.specialist_name,score,confidence,recommendation,tuple(evidence),flags)

class ChiefEconomist(Specialist):
    specialist_id="chief_economist"; specialist_name="Chief Economist"; specs=(SignalSpec("growth",.45),SignalSpec("employment",.25),SignalSpec("inflation",.15,False),SignalSpec("policy_support",.15))
class ChiefEquityStrategist(Specialist):
    specialist_id="chief_equity_strategist"; specialist_name="Chief Equity Strategist"; specs=(SignalSpec("earnings",.35),SignalSpec("equity_trend",.25),SignalSpec("breadth",.25),SignalSpec("valuation",.15))
class ChiefFixedIncomeStrategist(Specialist):
    specialist_id="chief_fixed_income_strategist"; specialist_name="Chief Fixed Income Strategist"; specs=(SignalSpec("credit",.35),SignalSpec("yield_curve",.25),SignalSpec("inflation",.20,False),SignalSpec("policy_support",.20))
class ChiefTechnicalStrategist(Specialist):
    specialist_id="chief_technical_strategist"; specialist_name="Chief Technical Strategist"; specs=(SignalSpec("equity_trend",.38),SignalSpec("momentum",.32),SignalSpec("breadth",.30))
class ChiefRiskOfficer(Specialist):
    specialist_id="chief_risk_officer"; specialist_name="Chief Risk Officer"; specs=(SignalSpec("volatility",.35,False),SignalSpec("credit",.25),SignalSpec("liquidity",.25),SignalSpec("breadth",.15))
class ChiefQuantitativeStrategist(Specialist):
    specialist_id="chief_quantitative_strategist"; specialist_name="Chief Quantitative Strategist"; specs=(SignalSpec("momentum",.30),SignalSpec("breadth",.25),SignalSpec("quality",.25),SignalSpec("valuation",.20))
class ChiefGlobalStrategist(Specialist):
    specialist_id="chief_global_strategist"; specialist_name="Chief Global Strategist"; specs=(SignalSpec("global_relative_strength",.45),SignalSpec("dollar",.20,False),SignalSpec("liquidity",.20),SignalSpec("growth",.15))
class ChiefCommodityStrategist(Specialist):
    specialist_id="chief_commodity_strategist"; specialist_name="Chief Commodity Strategist"; specs=(SignalSpec("commodities",.40),SignalSpec("inflation",.30),SignalSpec("dollar",.20,False),SignalSpec("growth",.10))
class ChiefValuationOfficer(Specialist):
    specialist_id="chief_valuation_officer"; specialist_name="Chief Valuation Officer"; specs=(SignalSpec("valuation",.65),SignalSpec("earnings",.20),SignalSpec("inflation",.15,False))
class ChiefQualityOfficer(Specialist):
    specialist_id="chief_quality_officer"; specialist_name="Chief Quality Officer"; specs=(SignalSpec("quality",.55),SignalSpec("earnings",.25),SignalSpec("credit",.20))
class ChiefBehavioralOfficer(Specialist):
    specialist_id="chief_behavioral_officer"; specialist_name="Chief Behavioral Officer"; specs=(SignalSpec("sentiment",.35,False),SignalSpec("positioning",.35,False),SignalSpec("momentum",.15),SignalSpec("breadth",.15))
class ChiefSectorRotationOfficer(Specialist):
    specialist_id="chief_sector_rotation_officer"; specialist_name="Chief Sector Rotation Officer"; specs=(SignalSpec("breadth",.30),SignalSpec("momentum",.30),SignalSpec("earnings",.25),SignalSpec("growth",.15))

DEFAULT_COUNCIL=(ChiefEconomist(),ChiefEquityStrategist(),ChiefFixedIncomeStrategist(),ChiefTechnicalStrategist(),ChiefRiskOfficer(),ChiefQuantitativeStrategist(),ChiefGlobalStrategist(),ChiefCommodityStrategist(),ChiefValuationOfficer(),ChiefQualityOfficer(),ChiefBehavioralOfficer(),ChiefSectorRotationOfficer())

def convene(snapshot:MarketSnapshot, specialists=DEFAULT_COUNCIL)->tuple[CouncilOpinion,...]: return tuple(s.evaluate(snapshot) for s in specialists)
