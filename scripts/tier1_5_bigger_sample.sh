#!/bin/bash
# Tier 1.5 follow-up: RIVER_OVERBET_NUTS_VS_LOOSE / TURN_OVERBET_NUTS_VS_LOOSE
# both landed inconclusive_small_effect at 144k/8k hands (2026-08-21
# re-check after the archetype restructure) -- magnitude shrunk close to
# zero but never went negative across 3 independent rounds. One more,
# much bigger attempt (1M-hand budget, tighter target_ci) to see if a
# real verdict (confirmed_positive or confirmed_negative) finally
# emerges, or if the true effect genuinely is too close to zero for any
# budget to resolve cleanly.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/tier1_5_bigger_sample_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  v27-river-overbet-nuts-vs-loose
  turn-overbet-nuts-vs-loose
)

echo "=== tier1.5 bigger sample started $(date) ===" | tee -a "$LOG"

for seed in 42 777; do
  for preset in "${PRESETS[@]}"; do
    echo "" | tee -a "$LOG"
    echo "### $preset (seed $seed) ###" | tee -a "$LOG"
    nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
      "$preset" 1000000 \
      --comparison current \
      --adaptive \
      --base-seed "$seed" \
      --target-ci 0.5 \
      --effect-ratio 0.5 \
      --min-hands 10000 \
      --max-hands 1000000 \
      --max-zero-divergent-hands 300000 \
      --chunk-size 2000 \
      --min-divergent 30 \
      --max-divergent 3000 \
      >> "$LOG" 2>&1
  done
done

echo "" | tee -a "$LOG"
echo "=== tier1.5 bigger sample finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
