#!/bin/bash
# Adaptive full-model ablation batch using next-card chance enumeration.
#
# Baseline is the current full ABC strategy. Treatment disables one active
# rule at a time, so reported delta is:
#   without_rule - full_model
#
# Negative delta means removing the rule costs EV, so the rule is helping.
set -e
cd "$(dirname "$0")/.."

TARGET_CI="${TARGET_CI:-1.0}"
EFFECT_RATIO="${EFFECT_RATIO:-0.5}"
MIN_HANDS="${MIN_HANDS:-5000}"
MAX_HANDS="${MAX_HANDS:-500000}"
MAX_ZERO_DIVERGENT_HANDS="${MAX_ZERO_DIVERGENT_HANDS:-50000}"
CHUNK_SIZE="${CHUNK_SIZE:-2000}"
MIN_DIVERGENT="${MIN_DIVERGENT:-30}"
MAX_DIVERGENT="${MAX_DIVERGENT:-2000}"
CONDITION_ARCHETYPES="${CONDITION_ARCHETYPES:-auto}"
LOG=/tmp/adaptive_chance_enumeration_ablation_$(date +%Y%m%d_%H%M%S).log

PRESETS=(
  r01-calling-raises
  r02-unconditional-cbet
  r03-opponent-aware-loose-call
  r04-wide-value-3bet
  r05-steal-wide-vs-nit
  r06-size-up-vs-nit-tag
  r07-wider-3bet-vs-loose
  r10-donk-bluff-vs-tight
  r12-tight-big-iso-limpers
  r14-bluff-3bet-vs-tight
)
if [[ -n "${PRESETS_OVERRIDE:-}" ]]; then
  read -r -a PRESETS <<< "$PRESETS_OVERRIDE"
fi

echo "=== adaptive full-model ablation run started $(date) ===" | tee -a "$LOG"
echo "target_ci=$TARGET_CI effect_ratio=$EFFECT_RATIO condition_archetypes=$CONDITION_ARCHETYPES min_hands=$MIN_HANDS max_hands=$MAX_HANDS max_zero_divergent_hands=$MAX_ZERO_DIVERGENT_HANDS chunk_size=$CHUNK_SIZE min_divergent=$MIN_DIVERGENT max_divergent=$MAX_DIVERGENT" | tee -a "$LOG"
echo "delta meaning: without_rule - full_model; negative means the rule helps" | tee -a "$LOG"

for preset in "${PRESETS[@]}"; do
  archetypes_arg=()
  archetypes_label="population"
  if [[ "$CONDITION_ARCHETYPES" == "auto" ]]; then
    case "$preset" in
      r03-opponent-aware-loose-call|v10-opponent-aware)
        archetypes_label="Loose-passive,Station,Maniac"
        ;;
      r05-steal-wide-vs-nit|v14-steal-wide)
        archetypes_label="Nit"
        ;;
      r06-size-up-vs-nit-tag|v14-size-target)
        archetypes_label="Nit,TAG"
        ;;
      r07-wider-3bet-vs-loose|v15-loose-3bet)
        archetypes_label="Maniac,Station"
        ;;
      r10-donk-bluff-vs-tight|v17-donk-bluff)
        archetypes_label="Nit,TAG,LAG"
        ;;
      r14-bluff-3bet-vs-tight|v24-bluff-3bet)
        archetypes_label="Nit,TAG,LAG"
        ;;
    esac
  elif [[ "$CONDITION_ARCHETYPES" != "population" && -n "$CONDITION_ARCHETYPES" ]]; then
    archetypes_label="$CONDITION_ARCHETYPES"
  fi
  if [[ "$archetypes_label" != "population" ]]; then
    archetypes_arg=(--archetypes "$archetypes_label")
  fi
  echo "" | tee -a "$LOG"
  echo "### $preset (ablation, archetypes=$archetypes_label) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
    --comparison ablation \
    "${archetypes_arg[@]}" \
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
echo "=== adaptive full-model ablation run finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
