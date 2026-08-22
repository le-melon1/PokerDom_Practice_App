#!/bin/bash
# A/B confirmation for three rules, all after the 2026-08-22 fix (opponent
# bots' own choose_bot_action calls now pass tilt_tier/bluff_tier_a/
# bluff_tier_c, so seated opponents actually behave differently, not just
# read differently by hero):
#   - wider-call-vs-tilting-opponent: RE-TEST with the bug fixed (previous
#     runs never had opponents actually behaving differently while tilting)
#   - bluff-catch-vs-frequent-bluffer-a: new, river-specific definition
#   - bluff-catch-vs-frequent-bluffer-c: new, any-street definition
# Sequential, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/tilt_and_bluff_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  wider-call-vs-tilting-opponent
  bluff-catch-vs-frequent-bluffer-a
  bluff-catch-vs-frequent-bluffer-c
)

echo "=== tilt+bluff confirm started $(date) ===" | tee -a "$LOG"

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
echo "=== tilt+bluff confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
