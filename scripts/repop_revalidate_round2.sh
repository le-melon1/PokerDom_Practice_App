#!/bin/bash
# Second round of re-validating abc_bot.py's archetype-gated strategies
# against the new preflop-only archetype system + retrained ML opponent
# model (2026-08-19/20 restructure). Round 1 covered the two biggest
# LOOSE_ARCHETYPES-adjacent levers (OPPONENT_AWARE_ARCHETYPES,
# WIDER_3BET_VS_LOOSE). This round covers every OTHER shipped-True flag
# that reads an opponent archetype-set membership, per user instruction
# "нужно проверить все флаги зависящие от типа игроков у нас же теперь
# они новые".
#
# Priority order: LOOSE_ARCHETYPES-gated flags first (Maniac/Station pop
# shifted the most), then BLUFF_3BET_VS_TIGHT (never modern-tested at
# all, independent of the restructure), then the TIGHT_ARCHETYPES_FOR_*
# family (Nit/TAG/LAG populations barely moved, lowest priority but
# still unchecked against the retrained ML model).
#
# Sequential, one process at a time, nice-d, both seeds -- same standard
# as every other batch this project uses.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/repop_revalidate_round2_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  v27-river-overbet-nuts-vs-loose
  turn-overbet-nuts-vs-loose
  float-flop-in-position
  v24-bluff-3bet
  v14-steal-wide
  v14-size-target
  r10-donk-bluff-vs-tight
  v25-barrel-bluff
  river-bluff-missed-draw
)

echo "=== repop revalidate round 2 started $(date) ===" | tee -a "$LOG"

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
echo "=== repop revalidate round 2 finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
