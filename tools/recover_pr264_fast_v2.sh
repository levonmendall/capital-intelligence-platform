#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
from pathlib import Path

path = Path("tools/recover_pr264_fast.sh")
content = path.read_text(encoding="utf-8")
anchor = "python tools/apply_comprehensive_market_discovery.py\n"
if content.count(anchor) != 1:
    raise RuntimeError(f"apply invocation anchor count is {content.count(anchor)}")
compatibility_patch = r'''python - <<'PATCHPY'
from pathlib import Path

path = Path("tools/apply_comprehensive_market_discovery.py")
content = path.read_text(encoding="utf-8")
old = '''\''    content = replace_once(
        content,
        '''    if direct_instruments:
        direct_client = DirectGlobalMarketClient()
        direct_symbols = tuple(item.symbol for item in direct_instruments)''',
        '''    if direct_instruments:
        direct_client = DirectGlobalMarketClient(
            DirectGlobalMarketUniverse(
                identifier=f"dynamic-direct-evidence:{universe.identifier}",
                provider_identifier="comprehensive-direct-market-evidence.v1",
                instruments=direct_instruments,
                limitations=universe.limitations,
            )
        )
        direct_symbols = tuple(item.symbol for item in direct_instruments)''',
        label="use dynamic direct client universe",
    )'''\'''
new = '''\''    content = replace_once(
        content,
        '''    if direct_instruments:
        direct_client = DirectGlobalMarketClient()
        for instrument in direct_instruments:''',
        '''    if direct_instruments:
        direct_client = DirectGlobalMarketClient(
            DirectGlobalMarketUniverse(
                identifier=f"dynamic-direct-evidence:{universe.identifier}",
                provider_identifier="comprehensive-direct-market-evidence.v1",
                instruments=direct_instruments,
                limitations=universe.limitations,
            )
        )
        for instrument in direct_instruments:''',
        label="use dynamic direct client universe",
    )'''\'''
if content.count(old) != 1:
    raise RuntimeError(f"dynamic direct client patch template count is {content.count(old)}")
path.write_text(content.replace(old, new, 1), encoding="utf-8")
PATCHPY

'''
content = content.replace(anchor, compatibility_patch + anchor, 1)
cleanup_anchor = "rm -f tools/recover_pr264_fast.sh\n"
if content.count(cleanup_anchor) != 1:
    raise RuntimeError(f"cleanup anchor count is {content.count(cleanup_anchor)}")
content = content.replace(
    cleanup_anchor,
    cleanup_anchor + "rm -f tools/recover_pr264_fast_v2.sh\n",
    1,
)
path.write_text(content, encoding="utf-8")
PY
exec bash tools/recover_pr264_fast.sh
