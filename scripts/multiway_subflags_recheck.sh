#!/bin/bash
# Re-check v18's 2026-08-07 individually-tested MULTIWAY_* sub-flags with
# the modern, much-lower-variance chance-enumeration method instead of the
# old whole-game simulation v18 used. Two of the three had clean old-method
# separation from zero; MULTIWAY_NARROW_CALL_RANGE was explicitly
# borderline (-3.96 with rake / +1.04 without, inside/at the edge of CI) --
# the most likely of the three to flip verdict here, same precedent as
# SIZE_UP_PREMIUM_OPENS. Sequential, one process at a time, nice-d, both
# seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/multiway_subflags_recheck_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  multiway-disable-air-cbet
  multiway-disable-loose-call
  multiway-narrow-call-range
)

echo "=== multiway subflags recheck started $(date) ===" | tee -a "$LOG"

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
echo "=== multiway subflags recheck finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
