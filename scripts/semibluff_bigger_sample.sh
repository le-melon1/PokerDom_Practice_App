#!/bin/bash
# SEMI_BLUFF_RAISE_DRAWS / SEMI_BLUFF_RAISE_DRAWS_TURN both showed a real
# reversal in the full re-validation sweep (2026-08-23): the turn version
# confirmed NEGATIVE on both seeds, the flop version negative-leaning on
# one seed and inconclusive on the other -- but on modest samples (6-14k
# hands, 30-110 divergent). Before flipping shipped True flags to False,
# get a much bigger, well-powered sample on both, both seeds -- same
# discipline as Tier 1.5 (RIVER/TURN_OVERBET_NUTS_VS_LOOSE), which looked
# similarly shaky on a small sample and resolved cleanly positive on a
# bigger one. This time the direction might genuinely be negative --
# find out properly either way.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/semibluff_bigger_sample_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  pf3-semi-bluff-raise-draws
  semi-bluff-raise-draws-turn
)

echo "=== semibluff bigger sample started $(date) ===" | tee -a "$LOG"

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
echo "=== semibluff bigger sample finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
