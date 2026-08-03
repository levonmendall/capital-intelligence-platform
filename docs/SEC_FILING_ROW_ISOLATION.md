# SEC filing row isolation

## Incident sequence

The retried August 3, 2026 canonical CIO cycle reached cross-market evidence
collection after the optional EODHD/LSE failure was isolated. The first SEC repair
showed that malformed individual filing rows could be excluded without discarding an
otherwise valid official filing history.

The next production run exposed the ASML pattern for CIK `0000937966`: six
consecutive malformed rows at indexes 585 through 590 in a 591-row submission set.
That established that a contiguous oldest-row suffix needed a distinct bounded policy.

A later retry reached Suncor Energy, CIK `0000311337`, and found eleven malformed
oldest rows at indexes 982 through 992 in a 993-row submission set. Those rows were
about 1.1 percent of the history and therefore remained inside the intended two-percent
policy, but an arbitrary ten-row ceiling blocked them. The fixed count was removed so
the policy is governed by data quality proportion and row location rather than issuer
history length.

## Correction

Production company evidence now applies two distinct bounded policies:

1. Structural failures remain blocking, including missing required columns and
   misaligned SEC parallel arrays.
2. Ordinary malformed rows remain limited to one percent of the row set, with a
   minimum allowance of one row.
3. A filing history containing at least 100 rows may exclude a contiguous malformed
   suffix only when it is the oldest part of the SEC array.
4. That trailing-history allowance is capped at two percent of the complete row set.
5. Recent, scattered, or middle-of-history corruption does not receive the trailing
   allowance.
6. If no valid rows remain or either percentage boundary is exceeded, the provider
   still fails closed.
7. Every valid row retains its original accession number, acceptance time, filing
   date, report date, form, document, retrieval time, and official archive URL.
8. Isolated rows are logged with the CIK, count, indexes, suffix classification,
   applied boundary, and policy version without logging filing contents or credentials.

## Governance boundary

This change does not fabricate a filing, infer a missing acceptance time, repair an SEC
value, alter the decision cutoff, lower an investment threshold, create a candidate,
authorize capital, change portfolio construction, or enable real money. It only keeps
a percentage-bounded legacy suffix from destroying the valid point-in-time filing
history that precedes it.
