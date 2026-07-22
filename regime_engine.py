from __future__ import annotations
import math
from .models import MarketSnapshot, RegimeResult

def _s(s: dict[str,float], key: str) -> float: return float(s.get(key,50))
def _positive(v: float)->float: return v-50
def _negative(v: float)->float: return 50-v

class ProbabilisticRegimeEngine:
    def __init__(self, temperature: float=12.0): self.temperature=max(1.0,float(temperature))
    def score(self, snapshot: MarketSnapshot) -> RegimeResult:
        s=snapshot.signals
        g,i,e,p,t,b,m,v,c,y,l=( _s(s,k) for k in ["growth","inflation","employment","policy_support","equity_trend","breadth","momentum","volatility","credit","yield_curve","liquidity"] )
        raw={
          "Expansion": 50 + .24*_positive(g)+.13*_positive(e)+.18*_positive(t)+.14*_positive(b)+.12*_positive(c)+.10*_positive(l)+.09*_negative(v),
          "Late Expansion":50+.18*_positive(g)+.22*_positive(i)+.15*_positive(t)+.12*_positive(c)+.15*_positive(v)+.18*_negative(y),
          "Slowdown":50+.25*_negative(g)+.12*_negative(e)+.15*_negative(b)+.12*_negative(m)+.13*_negative(c)+.13*_positive(v)+.10*_negative(y),
          "Recession":50+.28*_negative(g)+.18*_negative(e)+.15*_negative(c)+.12*_negative(t)+.10*_negative(b)+.12*_positive(v)+.05*_negative(l),
          "Recovery":50+.18*_negative(g)+.20*_positive(p)+.18*_positive(t)+.15*_positive(b)+.10*_positive(y)+.10*_positive(l)+.09*_negative(i),
          "Inflation Shock":50+.42*_positive(i)+.12*_positive(g)+.12*_positive(v)+.12*_negative(p)+.12*_negative(y)+.10*_negative(c),
          "Deflation Risk":50+.28*_negative(i)+.24*_negative(g)+.15*_negative(e)+.12*_negative(c)+.12*_negative(y)+.09*_positive(v),
          "High Volatility":50+.45*_positive(v)+.18*_negative(b)+.14*_negative(c)+.10*_negative(l)+.08*_negative(t)+.05*_negative(m)
        }
        raw={k:max(0,min(100,v)) for k,v in raw.items()}
        max_raw=max(raw.values()); exps={k:math.exp((v-max_raw)/self.temperature) for k,v in raw.items()}; z=sum(exps.values())
        probs={k:v/z for k,v in exps.items()}; ordered=sorted(probs.items(), key=lambda x:x[1], reverse=True)
        primary=ordered[0][0]; margin=ordered[0][1]-ordered[1][1]
        confidence=max(.5,min(.95,.55+margin*1.6))
        evidence=(f"Growth score {g:.0f}",f"Inflation score {i:.0f}",f"Trend/Breadth {t:.0f}/{b:.0f}",f"Volatility risk {v:.0f}",f"Credit conditions {c:.0f}")
        return RegimeResult(primary,probs,confidence,raw,evidence)
