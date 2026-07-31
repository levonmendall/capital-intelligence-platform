#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
from pathlib import Path

source = Path("tools/recover_pr264_fast.sh")
content = source.read_text(encoding="utf-8")
apply_anchor = "python tools/apply_comprehensive_market_discovery.py\n"
if content.count(apply_anchor) != 1:
    raise RuntimeError(f"apply invocation anchor count is {content.count(apply_anchor)}")

compatibility_patch = """python - <<'PATCHPY'
from pathlib import Path

path = Path("tools/apply_comprehensive_market_discovery.py")
lines = path.read_text(encoding="utf-8").splitlines()
marker = '        label="use dynamic direct client universe",'
matches = [index for index, line in enumerate(lines) if line == marker]
if len(matches) != 1:
    raise RuntimeError(f"dynamic direct-client marker count is {len(matches)}")
marker_index = matches[0]
start = next(
    index
    for index in range(marker_index, -1, -1)
    if lines[index] == "    content = replace_once("
)
end = next(
    index
    for index in range(marker_index + 1, len(lines))
    if lines[index] == "    )"
)
replacement = [
    "    content = replace_once(",
    "        content,",
    "        '''    if direct_instruments:",
    "        direct_client = DirectGlobalMarketClient()",
    "        for instrument in direct_instruments:''',",
    "        '''    if direct_instruments:",
    "        direct_client = DirectGlobalMarketClient(",
    "            DirectGlobalMarketUniverse(",
    "                identifier=f\"dynamic-direct-evidence:{universe.identifier}\",",
    "                provider_identifier=\"comprehensive-direct-market-evidence.v1\",",
    "                instruments=direct_instruments,",
    "                limitations=universe.limitations,",
    "            )",
    "        )",
    "        for instrument in direct_instruments:''',",
    "        label=\"use dynamic direct client universe\",",
    "    )",
]
lines[start:end + 1] = replacement
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PATCHPY

"""
content = content.replace(apply_anchor, compatibility_patch + apply_anchor, 1)
cleanup_anchor = "rm -f tools/recover_pr264_fast.sh\n"
if content.count(cleanup_anchor) != 1:
    raise RuntimeError(f"cleanup anchor count is {content.count(cleanup_anchor)}")
content = content.replace(
    cleanup_anchor,
    cleanup_anchor + "rm -f tools/recover_pr264_fast_v2.sh\n",
    1,
)
patched = Path("/tmp/recover_pr264_fast_v2_patched.sh")
patched.write_text(content, encoding="utf-8")
PY

exec bash /tmp/recover_pr264_fast_v2_patched.sh
