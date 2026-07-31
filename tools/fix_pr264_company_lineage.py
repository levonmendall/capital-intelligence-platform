"""Apply the one-line PR264 company-equity lineage correction and remove transport."""

from pathlib import Path

source = Path("production_paper_evidence.py")
content = source.read_text(encoding="utf-8")
section_marker = 'f"certification:paper-company-equity:{instrument.symbol}:"'
head, marker, tail = content.partition(section_marker)
if not marker:
    raise RuntimeError("company-equity lineage section is unavailable")
old = '                f"{\'DIRECT_MARKET\' if direct_market else \'ALPACA_IEX\'}:{instrument.symbol}",\n'
new = '                f"ALPACA_IEX:{instrument.symbol}",\n'
count = tail.count(old)
if count != 1:
    raise RuntimeError(
        f"expected one stale expression after the company-equity marker, found {count}"
    )
source.write_text(head + marker + tail.replace(old, new, 1), encoding="utf-8")

for path in (
    Path("tools/fix_pr264_company_lineage.py"),
    Path(".github/workflows/fix-pr264-company-lineage.yml"),
    Path(".github/workflows/fix-pr264-company-lineage-pr.yml"),
    Path(".pr264-company-lineage-trigger"),
):
    path.unlink(missing_ok=True)
