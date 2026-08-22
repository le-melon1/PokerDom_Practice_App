#!/bin/bash
# Full re-validation sweep: every confirmed-True flag in abc_bot.py that
# has NOT yet been individually re-tested against the post-2026-08-19/20
# archetype-restructure population + retrained ML opponent model (rounds
# 1+2 already covered every archetype-gated flag; this covers the rest --
# sizing rules, foundational rules, draw/street rules, etc. that don't
# read opponent_archetypes/freq_tier/tilt/bluff_tier at all but are still
# being tested against a fundamentally different opponent MODEL than when
# originally confirmed, since that model has been retrained 3 times this
# session).
#
# 19 flags with plain single-flag presets, tested identically to every
# other flag in this file's history. SHOVE_AA_KK_VS_3BET_PLUS handled
# separately below (needs --hero-hand-filter AA,KK, documented rarity).
# Sequential, nice-d, both seeds.
set -e
cd "$(dirname "$0")/.."

LOG=/tmp/full_revalidation_sweep_$(date +%Y%m%d_%H%M%S).log
PRESETS=(
  r27-set-mine-implied-odds
  sb-threebet-or-fold-vs-steal
  r22-threebet-size-by-position
  v23-size-strong
  v23-size-wet
  r12-tight-big-iso-limpers
  r21-tight-iso-real-data-floor
  r16v-limp-behind-plain
  r20-size-up-premium-opens
  v6-unconditional-cbet
  v3-calling-raises
  r23-threebet-bluff-late-position
  r19v-bb-defend-vs-steal-minraise-plain
  r24-bb-defend-mdf-scaled
  pf3-semi-bluff-raise-draws
  semi-bluff-raise-draws-turn
  pf4-nut-advantage-sizing
  pf7-spr-scaled-thresholds
  float-flop-in-position
)

echo "=== full revalidation sweep started $(date) ===" | tee -a "$LOG"

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
      --max-zero-divergent-hands 150000 \
      --chunk-size 2000 \
      --min-divergent 30 \
      --max-divergent 2000 \
      >> "$LOG" 2>&1
  done

  echo "" | tee -a "$LOG"
  echo "### r13-shove-aa-kk-vs-3bet-plus (seed $seed) ###" | tee -a "$LOG"
  nice -n 15 .venv/bin/python3 scripts/probe_chance_enumeration.py \
    r13-shove-aa-kk-vs-3bet-plus 500000 \
    --comparison current \
    --adaptive \
    --base-seed "$seed" \
    --target-ci 1.0 \
    --effect-ratio 0.5 \
    --min-hands 5000 \
    --max-hands 500000 \
    --max-zero-divergent-hands 150000 \
    --chunk-size 2000 \
    --min-divergent 30 \
    --max-divergent 2000 \
    --hero-hand-filter AA,KK \
    >> "$LOG" 2>&1
done

echo "" | tee -a "$LOG"
echo "=== full revalidation sweep finished $(date) ===" | tee -a "$LOG"
echo "Full log: $LOG"
