#!/bin/bash
# Adaptive confirmatory batch for every flag in the ledger that had never
# been statistically tested at all (as of 2026-08-16): TIGHT_ISO_INCLUDE_
# REAL_DATA_FLOOR, SIZE_UP_WITH_VERY_STRONG_HAND, SIZE_UP_ON_WET_BOARD,
# RIVER_OVERBET_NUTS_VS_LOOSE (v27, newly registered as a preset), the
# FOLD_PREMIUM_VS_EXTREME_AGGRO parameter sweep (r15v), the BB_DEFEND_VS_
# STEAL_MINRAISE parameter sweep (r19v), and two wider SHOVE_AA_KK_VS_
# 3BET_PLUS ranges (r18v-shove-qq-plus/qq-ak) that weren't covered by the
# earlier AA/KK-only r13 untestable finding. Sequential, one process at a
# time, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/remaining_untested_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  r21-tight-iso-real-data-floor
  v23-size-strong
  v23-size-wet
  v27-river-overbet-nuts-vs-loose
  r15v-fold-qq-vs-nit-tag-50
  r15v-fold-ak-vs-nit-tag-50
  r15v-fold-qq-ak-vs-nit-50
  r15v-fold-qq-ak-vs-nit-tag-75
  r19v-bb-defend-minraise-tight
  r19v-bb-defend-steal-medium
  r19v-bb-defend-steal-wide
  r18v-shove-qq-plus
  r18v-shove-qq-ak
)

echo "=== remaining-untested batch confirm started $(date) ===" | tee -a "$LOG"

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
echo "=== remaining-untested batch confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
