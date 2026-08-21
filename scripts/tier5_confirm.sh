#!/bin/bash
# A/B confirmation for the two Tier-5 backlog items coded 2026-08-21:
# FLOAT_TURN_IN_POSITION and SIZE_UP_PREMIUM_3BETS. Sequential, nice-d,
# both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/tier5_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  float-turn-in-position
  size-up-premium-3bets
)

echo "=== tier5 confirm started $(date) ===" | tee -a "$LOG"

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
      --max-zero-divergent-hands 150000 \
      --chunk-size 2000 \
      --min-divergent 30 \
      --max-divergent 2000 \
      >> "$LOG" 2>&1
  done
done

echo "" | tee -a "$LOG"
echo "=== tier5 confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
