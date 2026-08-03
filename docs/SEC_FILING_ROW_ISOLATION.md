# SEC filing row isolation

## Incident

The retried August 3, 2026 canonical CIO cycle reached cross-market evidence
collection after the optional EODHD/LSE failure was isolated. The SEC submissions
payload for one discovered company contained one malformed filing row at index 585.
The provider raised on that row and discarded all otherwise valid filing history,
which blocked the complete evidence collection and left the cycle without a briefing.

## Correction

Production company evidence now uses a bounded SEC filing-row parser:

1. Structural failures remain blocking, including missing required columns and
   misaligned SEC parallel arrays.
2. A small number of malformed individual rows may be excluded while all valid rows
   retain their original accession number, acceptance time, filing date, report date,
   form, document, retrieval time, and official archive URL.
3. The tolerance is limited to one percent of the SEC row set, with a minimum of one
   isolated row.
4. If no valid rows remain or malformed rows exceed that boundary, the provider still
   fails closed.
5. Isolated rows are logged with the CIK, count, indexes, and policy version without
   logging filing contents or credentials.

## Governance boundary

This change does not fabricate a filing, repair an SEC value, alter the decision
cutoff, lower an investment threshold, create a candidate, authorize capital, change
portfolio construction, or enable real money. It only prevents one invalid historical
row from destroying otherwise valid official SEC evidence.
