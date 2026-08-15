#!/bin/bash
# Adaptive confirmatory batch for r22-r29 (8 preflop research-pass flags,
# 2026-08-13, never statistically tested before). Sequential, one process
# at a time, nice-d, both seeds -- same pattern as pf_batch_confirm.sh.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/r22_29_batch_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  r22-threebet-size-by-position
  r23-threebet-bluff-late-position
  r24-bb-defend-mdf-scaled
  r25-bluff-3bet-blocker-range
  r26-limp-trap-monsters
  r27-set-mine-implied-odds
  r28-rake-adjusted-open-sizing
  r29-fold-vs-3bet-passive
)

echo "=== r22-r29 batch confirm started $(date) ===" | tee -a "$LOG"

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
echo "=== r22-r29 batch confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
