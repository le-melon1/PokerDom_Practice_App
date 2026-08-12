#!/bin/bash
# 2026-08-12: sequential run of every not-yet-confirmed preset variant,
# one at a time, nice-d.
#
# SKIPPED (not attempted below): v26-fold-premium-extreme, all four
# r15v-fold-*, and all three r18v-shove-* variants. All of them are gated
# on `n_raises>=2` (facing a 3bet+) THE SAME WAY r13 was -- confirmed via
# r13's own test (0 divergent over 50k hands even with hero's cards
# force-dealt to AA/KK, see CLAUDE.md). Forcing hero's hole cards alone
# doesn't fix this: reaching n_raises>=2 as the ACTOR needs an opponent to
# open, hero (or someone) to 3-bet, AND then a further re-raise before it's
# hero's turn again -- two independent rare opponent actions compounding in
# a population that barely 3-bets (2-5%) and 4-bets less. Confirming these
# for real needs conditioning the OPPONENT's action too (force an opener +
# a re-raiser), not just hero's cards -- a bigger addition to
# probe_chance_enumeration.py, not done yet. Don't re-add these to the
# queue without that.
#
# r16v-*/r17v/r19v-* below are all gated on "facing exactly one raise"
# (an open), a common spot -- no filter needed.
set -e
cd "$(dirname "$0")/.."
LOG=/tmp/remaining_variants_$(date +%Y%m%d_%H%M%S).log

run() {
  local preset="$1"; shift
  echo "### $preset ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py "$preset" --adaptive "$@" 2>&1 | tee -a "$LOG"
  echo "" | tee -a "$LOG"
}

echo "=== remaining variants run started $(date) ===" | tee -a "$LOG"

run r16v-limp-behind-tight --comparison current
run r16v-limp-behind-medium --comparison current
run r16v-limp-behind-wide --comparison current
run r17v-call-by-raiser-position --comparison current
run r19v-bb-defend-minraise-tight --comparison current
run r19v-bb-defend-steal-medium --comparison current
run r19v-bb-defend-steal-wide --comparison current
run v30-size-scaled-call --comparison historical

echo "=== remaining variants run finished $(date) ===" | tee -a "$LOG"
