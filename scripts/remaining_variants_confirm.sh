#!/bin/bash
# 2026-08-12: sequential run of every not-yet-confirmed preset variant
# (r15v-fold-*, r16v-*, r17v, r18v-*, r19v-*), one at a time, nice-d, with
# hero-hand-filter applied where the rule only fires on a specific hero
# hand (auto-inferred for the r15v-fold-* premium presets; explicit for
# r18v-shove-* since those are gated by SHOVE_VS_3BET_PLUS_RANGE, a
# different flag than FOLDABLE_PREMIUM_VS_EXTREME_AGGRO).
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

run v26-fold-premium-extreme --comparison historical
run r15v-fold-qq-vs-nit-tag-50 --comparison historical
run r15v-fold-ak-vs-nit-tag-50 --comparison historical
run r15v-fold-qq-ak-vs-nit-50 --comparison historical
run r15v-fold-qq-ak-vs-nit-tag-75 --comparison historical
run r16v-limp-behind-tight --comparison current
run r16v-limp-behind-medium --comparison current
run r16v-limp-behind-wide --comparison current
run r17v-call-by-raiser-position --comparison current
run r18v-shove-aa-kk --comparison current --hero-hand-filter AA,KK
run r18v-shove-qq-plus --comparison current --hero-hand-filter AA,KK,QQ
run r18v-shove-qq-ak --comparison current --hero-hand-filter AA,KK,QQ,AKs,AKo
run r19v-bb-defend-minraise-tight --comparison current
run r19v-bb-defend-steal-medium --comparison current
run r19v-bb-defend-steal-wide --comparison current

echo "=== remaining variants run finished $(date) ===" | tee -a "$LOG"
