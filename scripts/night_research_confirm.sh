#!/bin/bash
# Adaptive confirmatory batch for the 2026-08-17 "check sizings, SB strategy,
# postflop gaps" research pass. Sequential, one process at a time, nice-d,
# both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/night_research_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  r12v-published-theory
  sized-4bet-instead-of-shove
  sb-bigger-open-sizing
  sb-threebet-or-fold-vs-steal
  fold-marginal-vs-check-raise
  float-flop-in-position
)

echo "=== night research confirm started $(date) ===" | tee -a "$LOG"

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
echo "=== night research confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
