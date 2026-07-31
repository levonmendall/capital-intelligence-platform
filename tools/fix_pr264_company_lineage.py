"""Apply the one-line PR264 company-equity lineage correction and remove transport."""

from pathlib import Path

source = Path("production_paper_evidence.py")
content = source.read_text(encoding="utf-8")
old = '                f"{\'DIRECT_MARKET\' if direct_market else \'ALPACA_IEX\'}:{instrument.symbol}",\n'
new = '                f"ALPACA_IEX:{instrument.symbol}",\n'
count = content.count(old)
if count != 1:
    raise RuntimeError(f"expected one stale company lineage expression, found {count}")
source.write_text(content.replace(old, new, 1), encoding="utf-8")

for path in (
    Path("tools/fix_pr264_company_lineage.py"),
    Path(".github/workflows/fix-pr264-company-lineage.yml"),
    Path(".github/workflows/fix-pr264-company-lineage-pr.yml"),
    Path(".pr264-company-lineage-trigger"),
):
    path.unlink(missing_ok=True)
