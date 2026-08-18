#!/bin/bash
# Two candidates from "что ещё можно проверить" (2026-08-18), both
# flagged in abc_bot.py's own comments as separate, never-tested
# questions when their sibling rules shipped:
#   - semi-bluff-raise-draws-turn: extend pf3's flop-only semi-bluff raise
#     to the turn too.
#   - smaller-bluff-on-wet-board: the flip side of SIZE_UP_ON_WET_BOARD --
#     size a plain air bluff SMALLER (not bigger) on a wet board.
# Sequential, one process at a time, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/semibluff_turn_wetboard_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  semi-bluff-raise-draws-turn
  smaller-bluff-on-wet-board
)

echo "=== semibluff-turn / wetboard-bluff confirm started $(date) ===" | tee -a "$LOG"

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
echo "=== semibluff-turn / wetboard-bluff confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
