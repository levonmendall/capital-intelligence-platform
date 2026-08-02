# CIO Runtime and Continuity Remediation

## Scope

This correction closes three handoff defects that could prevent a qualified opportunity or ownership change from completing even though the strategy, evidence, and portfolio controls had approved continued consideration.

It does not change investment thresholds, the cash hurdle, specialist authority, CIO authority, construction limits, execution authority, or the paper-only boundary.

## 1. Runtime opportunity-context continuity

The governed publisher persisted the corrected competitive opportunity queue, but the runtime provider independently rebuilt qualified candidate alternatives using a different return and cost representation. The deployed CIO cycle could therefore consume a capital comparison that differed from the screening publication it was required to reproduce.

The publication now records the exact candidate-alternative membership used to form the final queue. The runtime provider consumes that membership and reconstructs those alternatives with the same net, horizon-normalized, evidence-adjusted comparable-return treatment. Current holdings are not duplicated, and implementation cost, evidence quality, and liquidity are not charged twice.

Older publications that predate the membership field remain readable through a qualified, non-held candidate fallback.

## 2. Hysteresis continuity

A material action deferred by hysteresis was previously persisted only as its temporary outward action:

- deferred `BUY` or `INCREASE` became `WATCH`;
- deferred `REDUCE` or `EXIT` became `HOLD`.

The prior-state reconstructor counted the outward action, so the intended supportive or opposing sequence could fail to advance. This could leave a multi-cycle entry, increase, reduction, or exit permanently deferred.

CIO decisions now preserve an optional typed `deferred_action` whenever hysteresis is applied. The append-only journal serializes that intent, and continuity reconstruction counts the intended action while retaining the outward action as the actual decision. Older records without the field keep their previous interpretation.

## 3. Portfolio-specialist capital comparison

The Portfolio and Risk specialist previously received the candidate's baseline cash-or-holding opportunity cost even when final qualification identified a stronger candidate-specific alternative. The preview construction edge and the CIO capital comparison could therefore disagree.

The final effective opportunity cost from qualification is now passed into portfolio preview, construction-edge calculation, and the specialist packet.

## Verification

Focused regression coverage confirms that:

- a deferred BUY counts as a supportive persistence cycle across timestamp-specific candidate identifiers;
- a deferred REDUCE counts as an opposing persistence cycle;
- runtime candidate-alternative membership matches the completed screening publication;
- runtime candidate alternatives do not receive duplicate implementation-cost, evidence, or liquidity penalties; and
- the Portfolio and Risk specialist receives the final candidate-specific effective opportunity cost.

The focused remediation suite also reruns decision-continuity, canonical CIO-cycle, governed publication, invested-candidate reachability, and competitive-opportunity regressions.

## State, migration, and rollback

No historical journal event, screening publication, or portfolio snapshot is rewritten. No database migration or portfolio reset is required. Revert the remediation commit to roll back.

## Authority boundary

- Canonical investment strategy changed: **no**
- Qualification threshold changed: **no**
- Probability threshold changed: **no**
- Cash hurdle changed: **no**
- Specialist authority changed: **no**
- CIO authority changed: **no**
- Construction authority changed: **no**
- Paper execution authority changed: **no**
- Real-money authority added: **no**
