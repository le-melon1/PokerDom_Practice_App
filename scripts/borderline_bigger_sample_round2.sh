#!/bin/bash
# Second bigger-sample push for the two remaining borderline results from
# the 2026-08-16 round (scripts/borderline_bigger_sample_confirm.sh, which
# used target-ci 0.5 / max-hands 1M):
#   - r26-limp-trap-monsters: split verdict, +0.16+/-0.32 (92k, seed42,
#     inconclusive) / +0.70+/-0.34 (160k, seed777, confirmed) -- genuinely
#     rare spot (unopened AA/KK), neither run got near the 1M cap, so a
#     tighter target-ci should actually buy more precision this time.
#   - pf8-block-bet-river: -0.78+/-0.77 (164k, seed42, confirmed_negative)
#     / -0.38+/-0.50 (348k, seed777, inconclusive) -- leans negative but
#     doesn't clear the bar on both seeds.
# Tighter target-ci (0.25 vs 0.5) than the last round, same 1M hand cap.
# Sequential, one process at a time, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/borderline_bigger_sample_round2_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  r26-limp-trap-monsters
  pf8-block-bet-river
)

echo "=== borderline bigger sample round 2 started $(date) ===" | tee -a "$LOG"

for seed in 42 777; do
  for preset in "${PRESETS[@]}"; do
    echo "" | tee -a "$LOG"
    echo "### $preset (seed $seed) ###" | tee -a "$LOG"
    nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
      "$preset" 1000000 \
      --comparison current \
      --adaptive \
      --base-seed "$seed" \
      --target-ci 0.25 \
      --effect-ratio 0.5 \
      --min-hands 20000 \
      --max-hands 1000000 \
      --max-zero-divergent-hands 150000 \
      --chunk-size 4000 \
      --min-divergent 30 \
      --max-divergent 3000 \
      >> "$LOG" 2>&1
  done
done

echo "" | tee -a "$LOG"
echo "=== borderline bigger sample round 2 finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
