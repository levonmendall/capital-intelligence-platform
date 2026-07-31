#!/usr/bin/env bash
set -Eeuo pipefail

git config user.name "capital-intelligence-automation"
git config user.email "actions@users.noreply.github.com"
git fetch origin main

if git merge --no-edit origin/main; then
  rm -rf .recovery
  rm -f tools/sync_pr274_with_main.sh
  rm -f .github/workflows/sync-pr274-with-main.yml
  rm -f .github/workflows/pr264-fast-materializer.yml
  python -m py_compile \
    operations/comprehensive_market_discovery.py \
    operations/free_paper_pilot.py \
    operations/direct_global_markets.py \
    production_paper_evidence.py \
    production_context_publication_governed.py \
    tests/test_comprehensive_market_discovery.py
  git add -A
  if ! git diff --cached --quiet; then
    git commit -m "Remove PR274 synchronization transport"
  fi
  git push origin HEAD:agent/recover-pr264-materialization
  exit 0
fi

conflicts=$(git diff --name-only --diff-filter=U)
git merge --abort
mkdir -p .recovery
printf '%s\n' "$conflicts" > .recovery/pr274-sync-conflicts.txt
git add .recovery/pr274-sync-conflicts.txt
git commit -m "Record PR274 current-main conflicts"
git push origin HEAD:agent/recover-pr264-materialization
exit 1
