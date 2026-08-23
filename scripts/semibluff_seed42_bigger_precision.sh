#!/bin/bash
# Follow-up to semibluff_bigger_sample.sh (2026-08-23). That whole run
# came back "confirmed_negative" on 3 of its 4 seed/preset combos, but
# every one of those confirmed_negative stops fired on a TINY divergent
# count (112, 44, 31) -- the adaptive stop rule's negative bar is looser
# than its positive bar (enum_ci <= abs(delta) vs enum_ci <=
# abs(delta)*0.5), so it can latch onto a noisy small-sample negative
# read very early. The 4th combo (pf3 flop, seed777) was NOT stopped
# early -- it ran all the way to max_divergent (3004 divergent hands)
# and converged to a SMALL POSITIVE effect (+0.82+/-0.55), the opposite
# sign of its own seed42 sibling's weak early stop. Same "underpowered
# negative reading, not a real reversal" pattern as this session's own
# Tier 1.5 precedent. Forcing --min-divergent up near --max-divergent
# bypasses the early confirmed_negative exit so these 3 under-sampled
# combos get the same sample depth pf3/seed777 got, for an honest
# apples-to-apples comparison before deciding these flags' fate.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/semibluff_seed42_bigger_precision_$(date +%Y%m%d_%H%M%S).log

echo "=== semibluff bigger precision followup started $(date) ===" | tee -a "$LOG"

run_one() {
  local preset="$1"
  local seed="$2"
  echo "" | tee -a "$LOG"
  echo "### $preset (seed $seed) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
    "$preset" 1000000 \
    --comparison current \
    --adaptive \
    --base-seed "$seed" \
    --target-ci 0.5 \
    --effect-ratio 0.5 \
    --min-hands 10000 \
    --max-hands 1000000 \
    --max-zero-divergent-hands 300000 \
    --chunk-size 2000 \
    --min-divergent 2900 \
    --max-divergent 3000 \
    >> "$LOG" 2>&1
}

run_one pf3-semi-bluff-raise-draws 42
run_one semi-bluff-raise-draws-turn 42
run_one semi-bluff-raise-draws-turn 777

echo "" | tee -a "$LOG"
echo "=== semibluff bigger precision followup finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
