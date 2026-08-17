#!/bin/bash
# Adaptive confirmatory batch for the last 3 postflop-gap flags (donk lead
# vs big bet w/ initiative, wet-board fold vs tight, missed-draw river
# bluff). All 3 are rare compound conditions (0 divergent at 300 hands in
# the smoke test) -- generous hand caps, matching the check-raise run
# earlier tonight. Sequential, one process at a time, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/postflop_gaps_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  fold-marginal-vs-big-donk
  fold-top-pair-vs-wet-board-tight
  river-bluff-missed-draw
)

echo "=== postflop gaps confirm started $(date) ===" | tee -a "$LOG"

for seed in 42 777; do
  for preset in "${PRESETS[@]}"; do
    echo "" | tee -a "$LOG"
    echo "### $preset (seed $seed) ###" | tee -a "$LOG"
    nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
      "$preset" 500000 \
      --comparison current \
      --adaptive \
      --base-seed "$seed" \
      --target-ci 1.0 \
      --effect-ratio 0.5 \
      --min-hands 5000 \
      --max-hands 500000 \
      --max-zero-divergent-hands 100000 \
      --chunk-size 2000 \
      --min-divergent 30 \
      --max-divergent 2000 \
      >> "$LOG" 2>&1
  done
done

echo "" | tee -a "$LOG"
echo "=== postflop gaps confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
