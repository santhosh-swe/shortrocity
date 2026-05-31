#!/usr/bin/env bash
# Continuous video-factory loop.
# Runs the factory over a plan, then sleeps and repeats. Completed videos are
# skipped on re-run (idempotent), so a loop keeps producing/repairing the batch.
# Usage: ./factory/run_loop.sh [plan.json] [out_dir] [sleep_seconds] [max_cycles]
set -uo pipefail
cd "$(dirname "$0")/.."

PLAN="${1:-factory/plan.json}"
OUT="${2:-storage/factory_out}"
SLEEP="${3:-1800}"          # 30 min between cycles by default
MAX="${4:-0}"              # 0 = run forever
PY=".venv/bin/python"

mkdir -p "$OUT"
cycle=0
while :; do
  cycle=$((cycle+1))
  echo "[$(date -u +%FT%TZ)] === factory cycle $cycle (plan=$PLAN) ==="
  PYTHONPATH=. "$PY" -m factory.factory "$PLAN" "$OUT" 2>&1 | grep -E "DONE|FAILED|BATCH|GateError" || true
  if [ "$MAX" -ne 0 ] && [ "$cycle" -ge "$MAX" ]; then
    echo "[$(date -u +%FT%TZ)] reached max cycles ($MAX), exiting"
    break
  fi
  echo "[$(date -u +%FT%TZ)] sleeping ${SLEEP}s before next cycle..."
  sleep "$SLEEP"
done
