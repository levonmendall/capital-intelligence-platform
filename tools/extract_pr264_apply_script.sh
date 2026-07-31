#!/usr/bin/env bash
set -euo pipefail
rm -rf /tmp/comprehensive-market-package
mkdir -p /tmp/comprehensive-market-package .recovery
cat \
  .comprehensive-market-discovery/payload.part00.0 \
  .comprehensive-market-discovery/payload.part00.1 \
  .comprehensive-market-discovery/payload.part00.2 \
  .comprehensive-market-discovery/payload.part00.3 \
  .comprehensive-market-discovery/payload.part01.0 \
  .comprehensive-market-discovery/payload.part01.1 \
  .comprehensive-market-discovery/payload.part01.2 \
  .comprehensive-market-discovery/payload.part01.3.0 \
  .comprehensive-market-discovery/payload.part01.3.1 \
  .comprehensive-market-discovery/payload.part01.3.2 \
  .comprehensive-market-discovery/payload.part01.3.3 \
  .comprehensive-market-discovery/payload.part01.3.4 \
  .comprehensive-market-discovery/payload.part01.3.5 \
  .comprehensive-market-discovery/payload.part01.3.6 \
  .comprehensive-market-discovery/payload.part02 \
  > /tmp/comprehensive-market-discovery.b64
echo "512c76e9da01d0f73def32c6553b3e6e290ccf7478aae775b7302e53b10af5c5  /tmp/comprehensive-market-discovery.b64" | sha256sum --check --strict
base64 --decode /tmp/comprehensive-market-discovery.b64 > /tmp/comprehensive-market-discovery.tar.gz
echo "0d600b7f2502f4da6e42b90f146f8642c051440206615a040155f10a8c721757  /tmp/comprehensive-market-discovery.tar.gz" | sha256sum --check --strict
tar --extract --gzip --file /tmp/comprehensive-market-discovery.tar.gz --directory /tmp/comprehensive-market-package
cp /tmp/comprehensive-market-package/tools/apply_comprehensive_market_discovery.py .recovery/apply_comprehensive_market_discovery.py
rm -f tools/extract_pr264_apply_script.sh
rm -f .github/workflows/pr264-inspect-package.yml
rm -f .comprehensive-market-discovery/inspect-trigger
git config user.name "capital-intelligence-automation"
git config user.email "actions@users.noreply.github.com"
git add -A
git commit -m "Capture PR264 package apply script for compatibility repair"
git push origin HEAD:agent/recover-pr264-materialization
