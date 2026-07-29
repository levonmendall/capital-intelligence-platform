# Immediate Paper Testing

## Governing rule

Paper testing may begin without a launch-clearance campaign or calendar delay.

## No longer required

The product does not require a frozen launch baseline, five-day burn-in, pre-entry
failure exercises, recovery certification, launch report, eligibility package,
human release decision, or runtime activation before paper execution.

## Controls that remain

Every paper implementation still requires:

- the `COMPOUNDING` paper portfolio and intact append-only portfolio state;
- an exact feasible CIO construction;
- exact authenticated user consent when execution originates in the application;
- a current certified eligible-universe publication and instrument identity;
- a paper-eligible instrument profile;
- a valid market session and current quote/FX evidence;
- liquidity, cost, cash, leverage, turnover, and drawdown safety limits;
- reconciled fills and append-only execution evidence;
- paper-only provider endpoints and `real_money_authorized=false`.

The standard safety limits remain a 35% maximum single-batch turnover and a 20%
portfolio drawdown stop. These are execution safeguards rather than launch
clearance.

## Optional institutional evidence

Operators may still run the campaign, launch, recovery, human-release, and runtime
control tools to create a formally certified test record. Their absence no longer
prevents product testing.
