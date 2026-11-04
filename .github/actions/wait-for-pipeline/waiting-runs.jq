# shortcut: equal timestamps do not block; add a run-ID tie-break if same-second starts need ordering.
[.[] .workflow_runs[]
 | select(.status == "in_progress" or .status == "queued")
 | select(.id != $run_id and .created_at < $created_at)
 | select(.name as $name | ["Daily pipeline", "Backfill", "Maintenance", "Resynthesize"] | index($name))]
| sort_by(.created_at, .id)
| .[0] // empty
| "waiting for run \(.id) (\(.name), created \(.created_at))"
