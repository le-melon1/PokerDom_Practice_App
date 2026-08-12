#!/bin/bash
# Adaptive confirmatory batch using next-card chance enumeration.
#
# Stops each preset once the EV delta is precise enough, or once hard caps are
# reached. Defaults:
#   confirmed: CI <= TARGET_CI and CI <= abs(delta) * EFFECT_RATIO
#   confirmed negative: delta < 0 and CI <= abs(delta)
#   small/inconclusive: CI <= TARGET_CI and abs(delta) < TARGET_CI
#   hard stop: MAX_HANDS or MAX_DIVERGENT
set -e
cd "$(dirname "$0")/.."

TARGET_CI="${TARGET_CI:-1.0}"
EFFECT_RATIO="${EFFECT_RATIO:-0.5}"
COMPARISON="${COMPARISON:-historical}"
MIN_HANDS="${MIN_HANDS:-10000}"
MAX_HANDS="${MAX_HANDS:-500000}"
MAX_ZERO_DIVERGENT_HANDS="${MAX_ZERO_DIVERGENT_HANDS:-50000}"
CHUNK_SIZE="${CHUNK_SIZE:-2000}"
MIN_DIVERGENT="${MIN_DIVERGENT:-30}"
MAX_DIVERGENT="${MAX_DIVERGENT:-2000}"
LOG=/tmp/adaptive_chance_enumeration_$(date +%Y%m%d_%H%M%S).log

PRESETS=(
  v11-multiway-aware
  v9-wide-3bet
  v14-steal-sizing
  v15-loose-3bet-turn
  v16-iso-limpers
  v17-donk-bluff
  v21-squeeze-wide
  v21-squeeze-size
  v21-squeeze-both
  v22-value-raise
  v22-value-raise-trips
  v23-overbet-fold
  v23-size-strong
  v23-size-wet
  v23-size-both
  v24-bluff-3bet
  v25-barrel-bluff
  v26-fold-premium-extreme
  v27-river-overbet
  v28-optimal-sizing
  v29-iso-wider-range
  v30-size-scaled-call
)
if [[ -n "${PRESETS_OVERRIDE:-}" ]]; then
  read -r -a PRESETS <<< "$PRESETS_OVERRIDE"
fi

echo "=== adaptive chance-enumeration run started $(date) ===" | tee -a "$LOG"
echo "target_ci=$TARGET_CI effect_ratio=$EFFECT_RATIO comparison=$COMPARISON min_hands=$MIN_HANDS max_hands=$MAX_HANDS max_zero_divergent_hands=$MAX_ZERO_DIVERGENT_HANDS chunk_size=$CHUNK_SIZE min_divergent=$MIN_DIVERGENT max_divergent=$MAX_DIVERGENT" | tee -a "$LOG"

for preset in "${PRESETS[@]}"; do
  preset_comparison="$COMPARISON"
  if [[ "$COMPARISON" == "historical" && "$preset" == "v9-wide-3bet" ]]; then
    preset_comparison="current"
  fi
  echo "" | tee -a "$LOG"
  echo "### $preset ($preset_comparison comparison) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
    --comparison "$preset_comparison" \
    --adaptive "$preset" \
    --target-ci "$TARGET_CI" \
    --effect-ratio "$EFFECT_RATIO" \
    --min-hands "$MIN_HANDS" \
    --max-hands "$MAX_HANDS" \
    --max-zero-divergent-hands "$MAX_ZERO_DIVERGENT_HANDS" \
    --chunk-size "$CHUNK_SIZE" \
    --min-divergent "$MIN_DIVERGENT" \
    --max-divergent "$MAX_DIVERGENT" \
    >> "$LOG" 2>&1
done

echo "" | tee -a "$LOG"
echo "=== adaptive chance-enumeration run finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
