#!/usr/bin/env bash
set -Eeuo pipefail

git config user.name "capital-intelligence-automation"
git config user.email "actions@users.noreply.github.com"
git fetch origin main

cleanup_and_publish() {
  rm -rf .recovery
  rm -f .pr274-sync-trigger .pr274-sync-trigger-v2
  rm -f tools/sync_pr274_with_main.sh
  rm -f .github/workflows/sync-pr274-with-main.yml
  rm -f .github/workflows/pr264-fast-materializer.yml
  rm -f .github/workflows/sync-pr274-controller.yml
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
}

if git merge --no-edit origin/main; then
  cleanup_and_publish
  exit 0
fi

mapfile -t conflicts < <(git diff --name-only --diff-filter=U)
if [[ "${#conflicts[@]}" -eq 1 && "${conflicts[0]}" == "render.yaml" ]]; then
  git checkout --theirs render.yaml
  git add render.yaml
  git commit --no-edit
  cleanup_and_publish
  exit 0
fi

printf -v conflict_text '%s\n' "${conflicts[@]}"
git merge --abort
mkdir -p .recovery
printf '%s' "$conflict_text" > .recovery/pr274-sync-conflicts.txt
git add .recovery/pr274-sync-conflicts.txt
git commit -m "Record PR274 current-main conflicts"
git push origin HEAD:agent/recover-pr264-materialization
exit 1
