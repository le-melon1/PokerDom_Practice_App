#!/bin/bash
# A/B confirmation for WIDER_CALL_VS_TILTING_OPPONENT, now using REAL
# live-accumulated tilt state (record_hand_for_tilt across this probe
# run's own hand sequence) instead of the earlier ground-truth per-hand
# sampling (which was inconclusive: seed42 confirmed_positive, seed777
# zero divergent hands). Sequential, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/tilt_confirm_live_$(date +%Y%m%d_%H%M%S).log

echo "=== tilt confirm (live) started $(date) ===" | tee -a "$LOG"

for seed in 42 777; do
  echo "" | tee -a "$LOG"
  echo "### wider-call-vs-tilting-opponent (seed $seed) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
    wider-call-vs-tilting-opponent 500000 \
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

echo "" | tee -a "$LOG"
echo "=== tilt confirm (live) finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
