#!/bin/bash
# First round of re-validating abc_bot.py's opponent-aware strategies
# against the new preflop-only archetype system + retrained ML opponent
# model (2026-08-19 restructure). Priority: the single biggest confirmed
# lever in the whole file (OPPONENT_AWARE_ARCHETYPES), then the one flag
# whose LOOSE_ARCHETYPES_FOR_3BET set explicitly includes Maniac
# (WIDER_3BET_VS_LOOSE -- also happens to be a Tier 1 "deliberately
# deferred" backlog item, so this doubles as that re-check).
# Sequential, one process at a time, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/repop_revalidate_round1_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  v10-opponent-aware
  v15-loose-3bet
)

echo "=== repop revalidate round 1 started $(date) ===" | tee -a "$LOG"

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
echo "=== repop revalidate round 1 finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
