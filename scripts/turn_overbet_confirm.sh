#!/bin/bash
# New idea from the "what else needs checking" list: per-opponent bluff-
# frequency exploitation turned out to need session-continuity simulation
# infra this project doesn't have yet (TableDossier stats accumulate
# across many hands at one table; probe_chance_enumeration.py samples one
# fresh hand at a time) -- out of scope for a quick check. Picked the
# tractable generalization instead: TURN_OVERBET_NUTS_VS_LOOSE, the same
# overbet-with-near-nuts-vs-loose-archetype idea RIVER_OVERBET_NUTS_VS_
# LOOSE already confirmed, extended off "river only" (never itself a
# tested restriction) to the turn. Sequential, one process at a time,
# nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/turn_overbet_confirm_$(date +%Y%m%d_%H%M%S).log

echo "=== turn overbet confirm started $(date) ===" | tee -a "$LOG"

for seed in 42 777; do
  echo "" | tee -a "$LOG"
  echo "### turn-overbet-nuts-vs-loose (seed $seed) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
    turn-overbet-nuts-vs-loose 500000 \
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

echo "" | tee -a "$LOG"
echo "=== turn overbet confirm finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
