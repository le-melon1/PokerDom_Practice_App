#!/bin/bash
# Sequential common-random confirmatory batch. Keep this separate from
# overnight_confirm_flags.sh so legacy and paired methodologies never mix.
set -e
cd "$(dirname "$0")/.."

N_HANDS="${1:-100000}"
LOG=/tmp/common_random_confirm_$(date +%Y%m%d_%H%M%S).log

echo "=== common-random confirmatory run started $(date) ===" | tee -a "$LOG"
echo "hands per arm: $N_HANDS" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "### [1/5] All flag presets (v9/v14/v15/v16/v17 + v25-v30) ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --common-random --flag-confirm all "$N_HANDS" >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [2/5] v24 BLUFF_3BET_VS_TIGHT ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --common-random --bluff-3bet "$N_HANDS" >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [3/5] sizing theory: SIZE_UP_WITH_VERY_STRONG_HAND / SIZE_UP_ON_WET_BOARD ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --common-random --sizing-theory "$N_HANDS" >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [4/5] FOLD_TOP_PAIR_VS_OVERBET ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --common-random --overbet-fold "$N_HANDS" >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "### [5/5] VALUE_RAISE tiers ###" | tee -a "$LOG"
nice -n 15 .venv/bin/python3 scripts/simulate_abc_bot.py --common-random --value-raise-tiers "$N_HANDS" >> "$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "=== common-random confirmatory run finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
