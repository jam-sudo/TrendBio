#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
filter() {
  jq -sr --argjson run_id "$1" --arg created_at "$2" -f waiting-runs.jq
}
# All four writer names block, in creation order, even across API pages.
for id in 101 102 103 104; do
  actual=$(jq --argjson id "$id" '.workflow_runs |= map(select(.id >= $id))' sample-runs.json |
    filter 105 '2026-11-04T13:30:00Z')
  expected=$(jq -r --argjson id "$id" '.workflow_runs[] | select(.id == $id) |
    "waiting for run \(.id) (\(.name), created \(.created_at))"' sample-runs.json)
  [[ "$actual" == "$expected" ]]
done
actual=$(jq '.workflow_runs |= map(select(.id >= 105))' sample-runs.json |
  filter 105 '2026-11-04T13:30:00Z')
[[ -z "$actual" ]] # Self, equal-time, younger, completed and unrelated runs do not block.
actual=$(filter 101 '2026-11-04T13:30:00Z' < sample-runs.json)
[[ "$actual" == 'waiting for run 102 (Backfill, created 2026-11-04T11:00:00Z)' ]]
actual=$(jq '.workflow_runs |= reverse' sample-runs.json |
  filter 105 '2026-11-04T13:30:00Z')
[[ "$actual" == 'waiting for run 101 (Daily pipeline, created 2026-11-04T10:00:00Z)' ]]
actual=$({ printf '{"workflow_runs":[]}\n'; cat sample-runs.json; } |
  filter 105 '2026-11-04T13:30:00Z')
[[ "$actual" == 'waiting for run 101 (Daily pipeline, created 2026-11-04T10:00:00Z)' ]]
[[ -z "$(printf '{"workflow_runs":[]}\n' | filter 105 '2026-11-04T13:30:00Z')" ]]
echo 'PASS: jq filter covers all four workflows, self exclusion, older-only ordering, statuses, unrelated workflows, pagination and empty results.'
