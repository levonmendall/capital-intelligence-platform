#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
from pathlib import Path

source = Path("tools/recover_pr264_fast.sh")
content = source.read_text(encoding="utf-8")
apply_anchor = "python tools/apply_comprehensive_market_discovery.py\n"
if content.count(apply_anchor) != 1:
    raise RuntimeError(f"apply invocation anchor count is {content.count(apply_anchor)}")
content = content.replace(
    apply_anchor,
    "python tools/patch_pr264_current_main.py\n" + apply_anchor,
    1,
)
cleanup_anchor = "rm -f tools/recover_pr264_fast.sh\n"
if content.count(cleanup_anchor) != 1:
    raise RuntimeError(f"cleanup anchor count is {content.count(cleanup_anchor)}")
content = content.replace(
    cleanup_anchor,
    cleanup_anchor
    + "rm -f tools/recover_pr264_fast_v2.sh\n"
    + "rm -f tools/patch_pr264_current_main.py\n",
    1,
)
patched = Path("/tmp/recover_pr264_fast_v2_patched.sh")
patched.write_text(content, encoding="utf-8")
PY

exec bash /tmp/recover_pr264_fast_v2_patched.sh
