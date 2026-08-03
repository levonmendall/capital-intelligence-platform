# SEC filing row isolation

## Incident sequence

The retried August 3, 2026 canonical CIO cycle reached cross-market evidence
collection after the optional EODHD/LSE failure was isolated. The first SEC repair
showed that malformed individual filing rows could be excluded without discarding an
otherwise valid official filing history.

Subsequent retries exposed bounded trailing legacy patterns in ASML and Suncor filing
histories. Those incidents established one-percent ordinary and two-percent contiguous
oldest-suffix controls.

The next retry reached Invesco QQQ Trust, Series 1, CIK `0001067839`. Twelve malformed
oldest rows were present in a 254-row SEC submission set. That count exceeded the
trailing percentage policy, but the production request was not asking for fund forms.
It requested only corporate annual forms: `10-K`, `10-K/A`, `20-F`, `20-F/A`, `40-F`,
and `40-F/A`.

The deeper defect was therefore filter order. The provider parsed and validated every
SEC submission row before applying the requested-form filter. Unrelated legacy fund
forms could block a corporate-facts request even though they were not evidence for the
query.

## Correction

Production company evidence now applies query scope before row validation:

1. Required SEC columns and aligned parallel arrays remain structural prerequisites.
2. A valid raw form is normalized first.
3. Rows outside the filing forms requested by the point-in-time query are skipped
   before acceptance, filing-date, report-date, accession, and document validation.
4. A missing or invalid form cannot be proven out of scope and therefore remains
   fail-closed.
5. Ordinary malformed rows inside the requested form scope remain limited to one
   percent, with a minimum allowance of one row.
6. An in-scope filing history containing at least 100 rows may exclude a contiguous
   malformed suffix only when it is the oldest part of the relevant SEC rows.
7. That in-scope trailing-history allowance remains capped at two percent.
8. Recent, scattered, middle-of-history, structural, or zero-usable-row corruption
   inside the requested evidence scope still fails closed.
9. Every retained row preserves its original accession number, acceptance time,
   filing date, report date, form, document, retrieval time, and official archive URL.
10. Diagnostics report complete and relevant row counts, requested forms, invalid
    indexes, suffix classification, applied boundary, and policy version without
    filing contents or credentials.

## Governance boundary

This change does not broaden acceptable corruption, infer a missing acceptance time,
repair an SEC value, fabricate a filing, alter the decision cutoff, lower an investment
threshold, create a candidate, authorize capital, change portfolio construction, or
enable real money. It prevents evidence outside the explicit filing-form query from
vetoing the evidence that was actually requested.
