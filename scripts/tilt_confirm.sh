#!/bin/bash
# A/B confirmation for WIDER_CALL_VS_TILTING_OPPONENT, ground-truth
# per-hand tilt sampling (see the flag's own comment in abc_bot.py).
# Sequential, nice-d, both seeds. Rare-ish spot (~4% opponent incidence x
# facing-a-bet x any-pair-or-better match), so allow a bigger max-hands
# budget than the freq_tier-style rules needed.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/tilt_confirm_$(date +%Y%m%d_%H%M%S).log

echo "=== tilt confirm started $(date) ===" | tee -a "$LOG"

for seed in 42 777; do
  echo "" | tee -a "$LOG"
  echo "### wider-call-vs-tilting-opponent (seed $seed) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
    wider-call-vs-tilting-opponent 1000000 \
    --comparison current \
    --adaptive \
    --base-seed "$seed" \
    --target-ci 1.0 \
    --effect-ratio 0.5 \
    --min-hands 5000 \
    --max-hands 1000000 \
    --max-zero-divergent-hands 300000 \
    --chunk-size 2000 \
    --min-divergent 30 \
    --max-divergent 3000 \
    >> "$LOG" 2>&1
done

echo "" | tee -a "$LOG"
echo "=== tilt confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
