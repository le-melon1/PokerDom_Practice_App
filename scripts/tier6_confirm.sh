#!/bin/bash
# A/B confirmation for two Tier 6 backlog items coded 2026-08-22:
# MULTIWAY_TIGHTEN_VS_SHORT_STACK_BEHIND and CONTINUOUS_FOLD_VS_BET_SIZE.
# Sequential, nice-d, both seeds. Both are slower per-hand than usual
# (more decision-point checks per divergent-candidate hand) and fairly
# rare spots, so a generous max-hands budget.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/tier6_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  multiway-tighten-vs-short-stack-behind
  continuous-fold-vs-bet-size
)

echo "=== tier6 confirm started $(date) ===" | tee -a "$LOG"

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
echo "=== tier6 confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
