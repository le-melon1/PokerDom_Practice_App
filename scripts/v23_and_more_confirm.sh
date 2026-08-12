#!/bin/bash
# 2026-08-12: fast adaptive re-test of v23 (sizing theories) and the
# overbet-fold theory via probe_chance_enumeration.py, replacing the much
# slower simulate_abc_bot.py 4-arm/1M-hand approach that got interrupted
# earlier by machine resource contention. historical comparison (v23 postdates
# v21-squeeze-wide's baseline set).
set -e
cd "$(dirname "$0")/.."
LOG=/tmp/v23_and_more_$(date +%Y%m%d_%H%M%S).log

run() {
  local preset="$1"; shift
  echo "### $preset ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py "$preset" --adaptive "$@" 2>&1 | tee -a "$LOG"
  echo "" | tee -a "$LOG"
}

echo "=== v23 + more run started $(date) ===" | tee -a "$LOG"

run v23-overbet-fold --comparison historical
run v23-size-strong --comparison historical
run v23-size-wet --comparison historical
run v23-size-both --comparison historical

echo "=== v23 + more run finished $(date) ===" | tee -a "$LOG"
