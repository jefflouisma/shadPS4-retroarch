#!/usr/bin/env bash
set -euo pipefail

: "${JULES_API_KEY:?JULES_API_KEY is required}"
: "${JULES_SOURCE:?JULES_SOURCE is required (e.g. sources/github/OWNER/REPO)}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${HEAD_REF:?HEAD_REF is required}"
: "${BASE_REF:?BASE_REF is required}"
: "${REPO_FULL_NAME:?REPO_FULL_NAME is required}"

JULES_API_BASE="${JULES_API_BASE:-https://jules.googleapis.com/v1alpha}"
JULES_AUTOMATION_MODE="${JULES_AUTOMATION_MODE:-AUTO_CREATE_PR}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not available on PATH" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required but not available on PATH" >&2
  exit 1
fi

git fetch origin "${BASE_REF}"

git checkout "${HEAD_REF}"

git pull --ff-only origin "${HEAD_REF}"

git config rerere.enabled true
git config rerere.autoupdate true

conflict_files=""
conflict_diff=""
if git merge --no-ff --no-commit "origin/${BASE_REF}"; then
  if git diff --cached --quiet; then
    echo "No upstream changes to merge; exiting."
  else
    echo "Merge is clean; no conflicts detected."
  fi
  git merge --abort || true
  exit 0
fi

conflict_files=$(git diff --name-only --diff-filter=U | tr '\n' ' ')
conflict_diff=$(git diff --merge || true)
git merge --abort

if [[ -z "${conflict_files}" ]]; then
  echo "Merge produced no conflict markers, skipping Jules resolution." >&2
  exit 1
fi

prompt=$(cat <<EOF
You are resolving Git merge conflicts for the shadPS4 fork.
Repository: ${REPO_FULL_NAME}
Base branch: ${BASE_REF}
Head branch: ${HEAD_REF}
Conflict files: ${conflict_files}

Rules:
- Preserve local shadPS4-retroarch changes unless upstream changes are required for compatibility.
- Prefer upstream when changes are identical or when local change is a superficial difference.
- Do not introduce new features; only resolve conflicts.
- Keep buildability on all existing platforms.
- Keep UI disabled for libretro in this fork.

Conflict diff:
${conflict_diff}
EOF
)

session_payload=$(jq -n \
  --arg prompt "${prompt}" \
  --arg source "${JULES_SOURCE}" \
  --arg startingBranch "${HEAD_REF}" \
  --arg title "Resolve merge conflicts for PR #${PR_NUMBER}" \
  --arg automationMode "${JULES_AUTOMATION_MODE}" \
  '{
    prompt: $prompt,
    sourceContext: {
      source: $source,
      githubRepoContext: {
        startingBranch: $startingBranch
      }
    },
    automationMode: $automationMode,
    title: $title
  }'
)

echo "Starting Jules session..."
session_response=$(curl -sS -X POST "${JULES_API_BASE}/sessions" \
  -H "Content-Type: application/json" \
  -H "X-Goog-Api-Key: ${JULES_API_KEY}" \
  -d "${session_payload}")

session_id=$(echo "${session_response}" | jq -r '.id // empty')
if [[ -z "${session_id}" ]]; then
  session_name=$(echo "${session_response}" | jq -r '.name // empty')
  session_id="${session_name##*/}"
fi

if [[ -z "${session_id}" ]]; then
  echo "Failed to create Jules session: ${session_response}" >&2
  exit 1
fi

echo "Jules session created: ${session_id}"

jules_pr_url=""
for attempt in $(seq 1 60); do
  session_status=$(curl -sS "${JULES_API_BASE}/sessions/${session_id}" \
    -H "X-Goog-Api-Key: ${JULES_API_KEY}")
  jules_pr_url=$(echo "${session_status}" | jq -r '.outputs[]?.pullRequest.url // empty' | head -n1)

  if [[ -n "${jules_pr_url}" ]]; then
    break
  fi

  echo "Waiting for Jules output (attempt ${attempt}/60)..."
  sleep 10
done

if [[ -z "${jules_pr_url}" ]]; then
  echo "Jules session did not produce a PR within timeout." >&2
  exit 1
fi

echo "Jules PR: ${jules_pr_url}"

jules_pr_number=$(echo "${jules_pr_url}" | awk -F/ '{print $NF}')
if [[ -z "${jules_pr_number}" ]]; then
  echo "Could not parse Jules PR number from URL." >&2
  exit 1
fi

temp_patch=$(mktemp)
gh pr diff "${jules_pr_number}" > "${temp_patch}"

if [[ ! -s "${temp_patch}" ]]; then
  echo "Jules PR diff is empty; aborting." >&2
  exit 1
fi

git checkout "${HEAD_REF}"
git pull --ff-only origin "${HEAD_REF}"

git apply --index "${temp_patch}"

git commit -m "Resolve merge conflicts via Jules"
git push origin "HEAD:${HEAD_REF}"

if [[ "${AUTO_MERGE:-false}" == "true" ]]; then
  echo "Enabling auto-merge for PR #${PR_NUMBER}"
  gh pr merge "${PR_NUMBER}" --auto --merge
fi
