#!/bin/bash
# 2026-08-11: sequential, large-N confirmatory runs for every A/B flag in
# abc_bot.py that's still "leans one way but doesn't clear the combined CI"
# at the sample sizes tested so far -- run ONE AT A TIME (not in parallel,
# per the resource-contention lessons from earlier today: two concurrent
# heavy jobs on this 8GB machine pushed it to 19.86GB of swap and hung it
# twice). Priority order: highest-value / most-likely-real first, in case
# the night ends before everything finishes.
#
# Usage: nohup caffeinate -i bash scripts/overnight_confirm_flags.sh > /tmp/overnight_confirm.log 2>&1 &
set -e
cd "$(dirname "$0")/.."
LOG=/tmp/overnight_confirm_$(date +%Y%m%d_%H%M%S).log
echo "=== overnight confirmatory run started $(date) ===" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "### [1/3] v24 BLUFF_3BET_VS_TIGHT at 2,000,000 hands/arm (was +2.56 bb/100 at 300k, inside ~2.9 CI) ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --bluff-3bet 2000000 >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [2/3] v23 sizing-theory (SIZE_UP_WITH_VERY_STRONG_HAND / SIZE_UP_ON_WET_BOARD) at 1,000,000 hands/arm (never tested at any scale) ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --sizing-theory 1000000 >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [3/3] Lower-priority flags already near-zero at 30-80k, re-confirming at 300k/500k ###" | tee -a "$LOG"

echo "--- FOLD_TOP_PAIR_VS_OVERBET (was +0.86 at 30k) ---" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --overbet-fold 500000 >> "$LOG" 2>&1

echo "--- VALUE_RAISE_TRIPS_OR_BETTER_ONLY (was -1.77 at 80k) ---" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --value-raise-tiers 500000 >> "$LOG" 2>&1

echo "=== overnight confirmatory run finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
