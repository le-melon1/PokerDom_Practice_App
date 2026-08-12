#!/bin/bash
# Sequential confirmatory batch using next-card chance enumeration by default.
#
# This is intentionally separate from common_random_confirm_all.sh:
# - use this when the question is "what is the lower-variance paired EV delta?";
# - use common_random_confirm_all.sh when the question is "what does the normal
#   full session simulator report under common random numbers?"
#
# Caveats are documented in scripts/probe_chance_enumeration.py. The important
# one: branches are averaged back into ONE observation per divergent hand, so
# the CI is not inflated by pretending 40 river cards are 40 independent hands.
set -e
cd "$(dirname "$0")/.."

N_HANDS="${1:-10000}"
LOG=/tmp/chance_enumeration_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  v11-multiway-aware
  v9-wide-3bet
  v14-steal-sizing
  v15-loose-3bet-turn
  v16-iso-limpers
  v17-donk-bluff
  v21-squeeze-wide
  v21-squeeze-size
  v21-squeeze-both
  v22-value-raise
  v22-value-raise-trips
  v23-overbet-fold
  v23-size-strong
  v23-size-wet
  v23-size-both
  v24-bluff-3bet
  v25-barrel-bluff
  v26-fold-premium-extreme
  v27-river-overbet
  v28-optimal-sizing
  v29-iso-wider-range
  v30-size-scaled-call
)

echo "=== chance-enumeration confirmatory run started $(date) ===" | tee -a "$LOG"
echo "hands per preset: $N_HANDS" | tee -a "$LOG"

for preset in "${PRESETS[@]}"; do
  echo "" | tee -a "$LOG"
  echo "### $preset ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py "$preset" "$N_HANDS" >> "$LOG" 2>&1
done

echo "" | tee -a "$LOG"
echo "=== chance-enumeration confirmatory run finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
