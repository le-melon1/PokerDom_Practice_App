#!/bin/bash
# 2026-08-12: re-run of every preset tested tonight with --comparison
# historical, now that HISTORICAL_PRIOR_ON_FLAGS is fixed (was missing
# ALLOW_CALLING_RAISES/UNCONDITIONAL_FLOP_CBET, crippling the baseline --
# see probe_chance_enumeration.py's v21-squeeze-wide comment and CLAUDE.md).
# v29 first since it was tonight's headline "confirmed positive" result and
# needs re-verification most urgently.
set -e
cd "$(dirname "$0")/.."
LOG=/tmp/refixed_historical_$(date +%Y%m%d_%H%M%S).log

run() {
  local preset="$1"; shift
  echo "### $preset ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py "$preset" --adaptive --comparison historical "$@" 2>&1 | tee -a "$LOG"
  echo "" | tee -a "$LOG"
}

echo "=== refixed historical run started $(date) ===" | tee -a "$LOG"

run v29-iso-wider-range
run v30-size-scaled-call
run v25-barrel-bluff
run v27-river-overbet
run v28-optimal-sizing
run v23-overbet-fold
run v23-size-strong
run v23-size-wet
run v23-size-both

echo "=== refixed historical run finished $(date) ===" | tee -a "$LOG"
