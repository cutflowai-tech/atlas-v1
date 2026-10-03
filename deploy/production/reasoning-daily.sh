#!/bin/sh
# Daily Reasoning V3 pass (waset-atlas-reasoning.service): the Change Gate on the published deterministic site, then `reason` for that
# run only when the gate created work. Unchanged evidence therefore makes no LLM call at all. Rollout switches, budgets and the
# breaker are the application's (reasoning.env); this script adds none. The hourly deterministic sync is separate and unchanged.
set -eu

ROOT=/opt/waset-atlas/current
COMPOSE="/usr/bin/docker compose --env-file /etc/waset-atlas/atlas.env --env-file /etc/waset-atlas/reasoning.env --project-directory $ROOT \
 -f $ROOT/deploy/production/compose.yaml -f $ROOT/deploy/production/compose.reasoning.yaml -f $ROOT/deploy/production/compose.reasoning-live.yaml"

gate=$($COMPOSE run --rm -T reasoning-ops gate /var/lib/waset-atlas/published/current)
printf '%s\n' "$gate"
work=$(printf '%s' "$gate" | python3 -c 'import json, sys; c = json.load(sys.stdin)["counts"]; print(c["llm_work_items"] + c["lifecycle_work_items"])')
run_id=$(printf '%s' "$gate" | python3 -c 'import json, sys; print(json.load(sys.stdin)["run_id"])')
if [ "$work" -eq 0 ]; then
    echo "reasoning: $run_id has no work (unchanged evidence); no reason pass"
    exit 0
fi
exec $COMPOSE run --rm -T reasoning-ops reason "$run_id"
