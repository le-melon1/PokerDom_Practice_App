#!/bin/bash
# 2026-08-11: sequential, large-N confirmatory runs for every A/B flag in
# abc_bot.py that's still "leans one way but doesn't clear the combined CI"
# (or was never tested at all) at the sample sizes tried so far -- run ONE
# AT A TIME (not in parallel, per the resource-contention lessons from
# earlier today: two concurrent heavy jobs on this 8GB machine pushed it to
# 19.86GB of swap and hung it twice). Priority order: the 5 flags that are
# currently LIVE (True) in the bot right now come first -- if any of them
# are actually net-negative, the bot is leaving money on the table (or
# losing it) with every hand played until this is resolved, unlike v22-24
# which are already shipped False and only affect future decisions once
# proven.
#
# Usage: nohup caffeinate -i bash scripts/overnight_confirm_flags.sh > /tmp/overnight_confirm.log 2>&1 &
set -e
cd "$(dirname "$0")/.."
LOG=/tmp/overnight_confirm_$(date +%Y%m%d_%H%M%S).log
echo "=== confirmatory run started $(date) ===" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "### [1/6] Legacy flags currently LIVE (True), never confirmed at real power -- 500k hands/arm each ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --flag-confirm all 500000 >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [2/6] v24 BLUFF_3BET_VS_TIGHT at 2,000,000 hands/arm (was +2.56 bb/100 at 300k, inside ~2.9 CI) ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --bluff-3bet 2000000 >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [3/6] v23 sizing-theory (SIZE_UP_WITH_VERY_STRONG_HAND / SIZE_UP_ON_WET_BOARD) at 1,000,000 hands/arm (never tested at any scale) ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --sizing-theory 1000000 >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [4/6] FOLD_TOP_PAIR_VS_OVERBET (was +0.86 at 30k) at 500k hands/arm ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --overbet-fold 500000 >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [5/6] VALUE_RAISE_TRIPS_OR_BETTER_ONLY (was -1.77 at 80k) at 500k hands/arm ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --value-raise-tiers 500000 >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [6/6] done -- see NEW-FEATURE tests (turn/river barrel bluff, 4bet-size folding) separately once built ###" | tee -a "$LOG"

echo "=== confirmatory run finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
