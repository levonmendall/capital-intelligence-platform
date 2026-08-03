# SEC filing row isolation

## Incident sequence

The retried August 3, 2026 canonical CIO cycle reached cross-market evidence
collection after the optional EODHD/LSE failure was isolated. Early retries showed that
isolated malformed SEC rows and bounded trailing legacy rows could otherwise discard
hundreds of valid filings.

Subsequent retries exposed three distinct scope problems:

1. ASML and Suncor histories contained bounded malformed oldest-row suffixes.
2. Invesco QQQ contained malformed legacy fund forms even though the production query
   requested only corporate annual forms.
3. STMicroelectronics, CIK `0000932787`, contained four malformed oldest annual-form
   rows among 32 requested-form rows and 963 total submissions. The company-facts
   payload did not reference those pre-XBRL filings, but the provider still validated
   them before joining facts to submission acceptance times.

The final defect was therefore not an insufficient corruption allowance. A
company-facts query was validating historical annual filings that could not contribute
a company fact.

## Correction

Production SEC evidence now uses two layers of query scope:

1. Required SEC columns and aligned parallel arrays remain structural prerequisites.
2. Filing queries validate every row inside the requested filing forms.
3. Company-facts queries first collect the accessions actually referenced by facts
   inside the requested forms.
4. Submission-row validation for company facts is limited to those referenced
   accessions.
5. An unreferenced pre-XBRL filing cannot veto a company-facts request because it is
   not evidence used by that request.
6. A referenced filing remains subject to the existing acceptance-time, filing-date,
   report-date, accession, document, row-quality, and point-in-time controls.
7. Missing referenced acceptance evidence causes the affected fact to remain
   unavailable; excessive malformed referenced rows still fail closed.
8. Ordinary malformed in-scope rows remain limited to one percent, with a minimum
   allowance of one row.
9. A sufficiently large in-scope history may exclude only a contiguous oldest-row
   suffix capped at two percent.
10. Missing columns, misaligned arrays, recent or scattered corruption, excessive
    relevant corruption, and zero usable relevant rows remain blocking.
11. Every retained record preserves its original SEC accession, acceptance time,
    filing date, report date, form, document, retrieval time, and official archive URL.
12. Diagnostics record complete-row, relevant-row, requested-form, requested-accession,
    invalid-index, policy-version, and applied-boundary metadata without filing contents
    or credentials.

## Governance boundary

This change does not broaden acceptable corruption, infer a missing acceptance time,
repair an SEC value, fabricate a filing, alter the decision cutoff, lower an investment
threshold, create a candidate, authorize capital, change portfolio construction, or
enable real money. It prevents SEC rows that cannot contribute to the requested
company-facts evidence from vetoing that evidence.
