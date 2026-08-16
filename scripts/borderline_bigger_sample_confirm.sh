#!/bin/bash
# Re-test every flag currently sitting on a split/inconclusive verdict, at
# much higher hand caps, to see if more power resolves the ambiguity.
# Sequential, one process at a time, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/borderline_bigger_sample_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  pf5-probe-bet-turn-after-check
  pf8-block-bet-river
  r26-limp-trap-monsters
  r17v-call-by-raiser-position
  v27-river-overbet-nuts-vs-loose
)

echo "=== borderline bigger-sample confirm started $(date) ===" | tee -a "$LOG"

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
      --min-hands 20000 \
      --max-hands 1000000 \
      --max-zero-divergent-hands 100000 \
      --chunk-size 4000 \
      --min-divergent 50 \
      --max-divergent 4000 \
      >> "$LOG" 2>&1
  done
done

echo "" | tee -a "$LOG"
echo "=== borderline bigger-sample confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
