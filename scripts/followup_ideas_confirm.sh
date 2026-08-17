#!/bin/bash
# Adaptive confirmatory batch for the 4 follow-up ideas raised while
# explaining preflop/postflop strategy (2026-08-17, later session):
#   - sb-open-3.5bb: re-test SB_BIGGER_OPEN_SIZING at 3.5bb (3.0bb was
#     inconclusive)
#   - tight-iso-vs-wide-iso-headtohead: real head-to-head between the two
#     limper-isolation mechanisms (ISO_WIDER_RANGE_OVER_LIMPERS is
#     currently structurally dead code, shadowed by TIGHT_BIG_ISO_RAISE_
#     LIMPERS)
#   - sb-flat-call-vs-fold-diagnostic: absolute EV of SB's flat-call range
#     vs a steal, compared to folding (not compared to 3-betting) --
#     answers whether SB_THREEBET_OR_FOLD_VS_STEAL's win is masking a weak
#     OOP postflop game
#   - tight-iso-tightens-per-limper: narrow the tight-iso range further
#     per limper beyond the first, not just sizing
# Sequential, one process at a time, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/followup_ideas_confirm_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  sb-open-3.5bb
  tight-iso-vs-wide-iso-headtohead
  sb-flat-call-vs-fold-diagnostic
  tight-iso-tightens-per-limper
)

echo "=== followup ideas confirm started $(date) ===" | tee -a "$LOG"

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
echo "=== followup ideas confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
