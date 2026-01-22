#!/usr/bin/env bash
set -euo pipefail

: "${UPSTREAM_REPO:?UPSTREAM_REPO is required}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"

if ! git remote get-url upstream >/dev/null 2>&1; then
  git remote add upstream "https://github.com/${UPSTREAM_REPO}.git"
fi

git fetch upstream "${UPSTREAM_BRANCH}"

git config rerere.enabled true
git config rerere.autoupdate true

git config user.name "${GIT_USER_NAME:-github-actions[bot]}"
git config user.email "${GIT_USER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"

merge_result="clean"
if ! git merge --no-ff --no-commit "upstream/${UPSTREAM_BRANCH}"; then
  merge_result="conflict"
fi

if [[ "$merge_result" == "clean" ]]; then
  if git diff --cached --quiet; then
    echo "No upstream changes to merge."
    echo "merge_result=none" >> "${GITHUB_OUTPUT}"
    exit 0
  fi

  git commit -m "Sync upstream ${UPSTREAM_REPO}@${UPSTREAM_BRANCH}"
  git push origin HEAD:main
  echo "merge_result=merged" >> "${GITHUB_OUTPUT}"
  exit 0
fi

git merge --abort

sync_branch="sync/upstream-$(date +%Y%m%d)"

git checkout -B "${sync_branch}" "upstream/${UPSTREAM_BRANCH}"

git push --force-with-lease origin "${sync_branch}"

echo "merge_result=conflict" >> "${GITHUB_OUTPUT}"
echo "sync_branch=${sync_branch}" >> "${GITHUB_OUTPUT}"
