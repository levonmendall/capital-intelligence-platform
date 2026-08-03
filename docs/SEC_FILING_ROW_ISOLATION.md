# SEC filing row isolation

## Incident sequence

The retried August 3, 2026 canonical CIO cycle reached cross-market evidence
collection after the optional EODHD/LSE failure was isolated. The first SEC repair
showed that malformed individual filing rows could be excluded without discarding an
otherwise valid official filing history.

The next production run exposed the complete ASML pattern for CIK `0000937966`: six
consecutive malformed rows at indexes 585 through 590 in a 591-row submission set.
The original one-percent floor allowed five rows, so the provider correctly remained
fail-closed and reported the exact boundary rather than silently broadening it.

## Correction

Production company evidence now applies two distinct bounded policies:

1. Structural failures remain blocking, including missing required columns and
   misaligned SEC parallel arrays.
2. Ordinary malformed rows remain limited to one percent of the row set, with a
   minimum allowance of one row.
3. A filing history containing at least 100 rows may exclude a contiguous malformed
   suffix only when it is the oldest part of the SEC array.
4. That trailing-history allowance is bounded at two percent and never more than ten
   rows.
5. Recent, scattered, or middle-of-history corruption does not receive the trailing
   allowance.
6. If no valid rows remain or either policy boundary is exceeded, the provider still
   fails closed.
7. Every valid row retains its original accession number, acceptance time, filing
   date, report date, form, document, retrieval time, and official archive URL.
8. Isolated rows are logged with the CIK, count, indexes, suffix classification,
   applied boundary, and policy version without logging filing contents or credentials.

## Governance boundary

This change does not fabricate a filing, infer a missing acceptance time, repair an SEC
value, alter the decision cutoff, lower an investment threshold, create a candidate,
authorize capital, change portfolio construction, or enable real money. It only keeps
a tightly bounded legacy suffix from destroying the valid point-in-time filing history
that precedes it.
