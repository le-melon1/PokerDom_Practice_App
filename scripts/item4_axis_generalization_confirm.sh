#!/bin/bash
# Item 4 (axis generalization): full both-seed confirmation batch for the
# two new flags built this round that OR a freq_tier-based condition
# alongside an existing archetype-based one -- BLUFF_VS_RARE_TIER
# (generalizes the tight-archetype bluff gate to also fire vs
# postflop_freq_tier=rare) and WIDER_3BET_VS_OFTEN_TIER (generalizes
# WIDER_3BET_VS_LOOSE to also fire vs postflop_freq_tier=often). Both
# were coded and smoke-tested only so far -- this is their first real
# adaptive statistical confirmation, same standard as every other flag
# in this file (both seeds, confirmed_positive/negative/inconclusive).
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/item4_axis_generalization_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  bluff-vs-rare-tier
  wider-3bet-vs-often-tier
)

echo "=== item4 axis generalization confirm started $(date) ===" | tee -a "$LOG"

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
echo "=== item4 axis generalization confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
