#!/bin/bash
# 2026-08-12: cross-check tonight's confirmed/flipped results (v29, v30,
# v25, v28) against a genuinely independent second sample (--base-seed 777,
# not the same seed=42 every other run tonight used) -- this project's own
# standard requires two independent confirmations before calling something
# permanently confirmed.
set -e
cd "$(dirname "$0")/.."
LOG=/tmp/independent_seed_$(date +%Y%m%d_%H%M%S).log

run() {
  local preset="$1"; shift
  echo "### $preset (base_seed=777) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py "$preset" --adaptive --comparison historical --base-seed 777 "$@" 2>&1 | tee -a "$LOG"
  echo "" | tee -a "$LOG"
}

echo "=== independent seed run started $(date) ===" | tee -a "$LOG"

run v29-iso-wider-range
run v30-size-scaled-call
run v25-barrel-bluff
run v28-optimal-sizing

echo "=== independent seed run finished $(date) ===" | tee -a "$LOG"
