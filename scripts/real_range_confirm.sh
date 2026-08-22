#!/bin/bash
# A/B confirmation for REAL_RANGE_NUT_ADVANTAGE_SIZING (Tier 6 #3).
# NUT_ADVANTAGE_SIZING (the old rank/wet-dry proxy) is already True by
# default in BOTH arms of this comparison, so divergence only occurs
# where the real Monte Carlo equity read DISAGREES with the proxy --
# rarer than a typical flag test, and each hand costs real Monte Carlo
# compute (~13ms/hand measured in smoke testing, vs <1ms for most other
# presets in this file). Sequential, nice-d, both seeds, generous budget.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/real_range_confirm_$(date +%Y%m%d_%H%M%S).log

echo "=== real range confirm started $(date) ===" | tee -a "$LOG"

for seed in 42 777; do
  echo "" | tee -a "$LOG"
  echo "### real-range-nut-advantage-sizing (seed $seed) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
    real-range-nut-advantage-sizing 300000 \
    --comparison current \
    --adaptive \
    --base-seed "$seed" \
    --target-ci 1.0 \
    --effect-ratio 0.5 \
    --min-hands 5000 \
    --max-hands 300000 \
    --max-zero-divergent-hands 150000 \
    --chunk-size 2000 \
    --min-divergent 30 \
    --max-divergent 1500 \
    >> "$LOG" 2>&1
done

echo "" | tee -a "$LOG"
echo "=== real range confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
