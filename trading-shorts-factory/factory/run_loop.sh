#!/usr/bin/env bash
# Perpetual content engine.
# Invents fresh topics every cycle, renders them, de-dupes against everything
# produced so far, and rebuilds a cumulative POSTING_PACK.md — an ever-growing
# review queue. Runs until you stop it (Ctrl-C is safe; the registry is saved
# after every video).
#
# Usage: ./factory/run_loop.sh [n_per_cycle] [out_dir] [sleep_seconds] [max_cycles]
#        n_per_cycle  videos to invent+render each cycle   (default 3)
#        sleep_seconds pause between cycles                (default 1800 = 30m)
#        max_cycles   0 = run forever                      (default 0)
set -uo pipefail
cd "$(dirname "$0")/.."

N="${1:-3}"
OUT="${2:-storage/factory_out}"
SLEEP="${3:-1800}"
MAX="${4:-0}"

exec env PYTHONUNBUFFERED=1 PYTHONPATH=. .venv/bin/python -m factory.autoloop "$N" "$OUT" "$SLEEP" "$MAX"
