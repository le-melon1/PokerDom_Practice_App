#!/bin/bash
# Adaptive confirmatory batch for pf1-pf10 (pf2 excluded, covered by existing
# multiway preset). Sequential, one process at a time, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/pf_batch_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  pf1-texture-dependent-cbet-sizing
  pf3-semi-bluff-raise-draws
  pf4-nut-advantage-sizing
  pf5-probe-bet-turn-after-check
  pf6-pot-control-marginal-hands
  pf7-spr-scaled-thresholds
  pf8-block-bet-river
  pf9-blocker-based-river-bluff
  pf10-delayed-cbet-marginal
)

echo "=== pf batch confirm started $(date) ===" | tee -a "$LOG"

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
      --max-zero-divergent-hands 50000 \
      --chunk-size 2000 \
      --min-divergent 30 \
      --max-divergent 2000 \
      >> "$LOG" 2>&1
  done
done

echo "" | tee -a "$LOG"
echo "=== pf batch confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
