#!/bin/bash
# Bigger-sample re-checks for the pokerdom_pending_ideas backlog, per user
# instruction "продолжай всё делать по плану":
# - RIVER_OVERBET_NUTS_VS_LOOSE / TURN_OVERBET_NUTS_VS_LOOSE: round-2
#   re-validation held direction both seeds but seed42 didn't clear CI
#   cleanly (inconclusive_small_effect) -- bigger max-hands budget to see
#   if that resolves with more data.
# - USE_WIDE_VALUE_3BET (v9): last remaining Tier-1 "old method only"
#   backlog item -- WIDER_3BET_VS_LOOSE and STEAL_WIDER_VS_NIT are already
#   resolved, this is the last of the original three.
# - FOLD_VS_3BET_FROM_PASSIVE (r29): seed777 had zero divergent hands in
#   50k before -- much bigger max-hands budget to see if it's genuinely
#   untestable (like STEAL_WIDER_VS_NIT) or just needed more hands.
# - OPTIMAL_VALUE_SIZING_PER_ARCHETYPE (v28): sign already solid (5/5
#   positive), this is about pinning down a precise magnitude with a
#   bigger single run.
# Sequential, nice-d, both seeds where applicable.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/pending_backlog_round1_$(date +%Y%m%d_%H%M%S).log
echo "=== pending backlog round 1 started $(date) ===" | tee -a "$LOG"

for seed in 42 777; do
  for preset in v27-river-overbet-nuts-vs-loose turn-overbet-nuts-vs-loose v9-wide-3bet; do
    echo "" | tee -a "$LOG"
    echo "### $preset (seed $seed) ###" | tee -a "$LOG"
    nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
      "$preset" 1000000 \
      --comparison current \
      --adaptive \
      --base-seed "$seed" \
      --target-ci 1.0 \
      --effect-ratio 0.5 \
      --min-hands 5000 \
      --max-hands 1000000 \
      --max-zero-divergent-hands 200000 \
      --chunk-size 2000 \
      --min-divergent 30 \
      --max-divergent 3000 \
      >> "$LOG" 2>&1
  done
done

# FOLD_VS_3BET_FROM_PASSIVE: seed42 was already confirmed negative before;
# this reruns both for consistency but the real question is whether
# seed777 finally gets divergent hands with a much bigger budget.
for seed in 42 777; do
  echo "" | tee -a "$LOG"
  echo "### r29-fold-vs-3bet-passive (seed $seed) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
    r29-fold-vs-3bet-passive 1000000 \
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

# OPTIMAL_VALUE_SIZING_PER_ARCHETYPE: one big single-seed run to pin down
# magnitude (sign already solid from 5 prior independent samples).
echo "" | tee -a "$LOG"
echo "### v28-optimal-sizing (seed 42, big N) ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
  v28-optimal-sizing 1000000 \
  --comparison current \
  --adaptive \
  --base-seed 42 \
  --target-ci 0.5 \
  --effect-ratio 0.3 \
  --min-hands 5000 \
  --max-hands 1000000 \
  --max-zero-divergent-hands 200000 \
  --chunk-size 2000 \
  --min-divergent 30 \
  --max-divergent 3000 \
  >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "=== pending backlog round 1 finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
