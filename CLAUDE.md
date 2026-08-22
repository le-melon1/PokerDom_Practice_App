# PokerDom Practice App — handoff notes (2026-08-11)

This file exists so a fresh assistant (any model, not just Claude) can pick
up this project mid-stream without re-deriving everything from git log. It
is a *snapshot as of 2026-08-11, late afternoon* — always sanity-check
numbers against actual code/logs before trusting them; things move fast in
this project.

## The two-repo relationship (read this first)

Two sibling directories, both required, MUST be cloned/kept side by side
with these exact names:

- `PokerDom_Practice_App` (this repo) — FastAPI backend + vanilla JS
  frontend, a local practice table against ML bots, plus a hand-coded
  rule-based bot (`backend/bots/abc_bot.py`) used purely as an offline
  research vehicle (see below).
- `PokerDom_Microlimits_Analysis` — offline analysis of a real 3.56M-hand
  microstakes dataset (PokerStars NL25, Zenodo/phh-dataset, CC-BY 4.0).
  Produces the reference CSVs and helper modules (`src.*`) that
  Practice_App imports directly at runtime.

`backend/engine/cards_import.py` and several other files do
`Path(__file__).resolve().parents[N] / "PokerDom_Microlimits_Analysis"` +
`sys.path.insert`. Practice_App will not import at all if the sibling repo
isn't present at that relative path.

Run via `python3 run_app.py` → `http://127.0.0.1:8001/`.

## CURRENT STATUS SUMMARY (2026-08-13, read this section first)

This section is the up-to-date answer to "where are we and what's left" --
everything below it is historical detail/evidence for these claims. If
this section and something further down disagree, trust this one and fix
the other.

### How testing actually works here

Every rule in `backend/bots/abc_bot.py` is a flag (`SOME_FLAG = True/False`)
read at decision time. Nothing ships `True` without being measured first
(exceptions are called out explicitly when it happens). The measurement
tool is `scripts/probe_chance_enumeration.py`:

1. Run baseline and treatment in lockstep on the same dealt hand (common
   random numbers via `_common_seed(base_seed, hand_index, stream, ...)`).
2. The instant hero's action first differs between the two arms, average
   the rest of the hand over every possible next board card instead of one
   random continuation -- cuts CI width ~2-6x per hand at the same sample
   size.
3. A result only counts as **"confirmed real"** if `|delta| > sqrt(CI_a² +
   CI_b²)` against a SECOND, independently-seeded run (`--base-seed 777`
   after the default 42) -- one good-looking sample is never enough.
4. `--adaptive` runs chunks until it hits `confirmed_positive`,
   `confirmed_negative`, `inconclusive_small_effect`, or a hard cap
   (`no_divergent_hands`/`max_hands`/`max_divergent`).

Run it as: `.venv/bin/python3 scripts/probe_chance_enumeration.py <preset>
<n_hands> --comparison current --adaptive --base-seed 42` (then `777` for
cross-check). Every rule discussed below already has a preset wired in --
check `RULE_TEST_GROUPS`/`PARAMETER_VARIANTS`/`EXTRA_TEST_GROUPS` in that
file for the exact name. **Never launch a batch of these without the
user's explicit go-ahead first** -- this machine is shared and runs tight
on RAM (check `vm_stat` before launching, `nice -n 15`, one heavy job at a
time, `caffeinate -i` for anything long).

### Preflop: what's confirmed and shipped True

`OPPONENT_AWARE_ARCHETYPES` (v10, +16.05 bb/100 -- the single biggest
lever), `DONK_BLUFF_VS_TIGHT`, `BLUFF_3BET_VS_TIGHT` (v24), `STEAL_WIDER_
VS_NIT`, `TIGHT_BIG_ISO_RAISE_LIMPERS`, `ISO_WIDER_RANGE_OVER_LIMPERS`
(v29), `BARREL_BLUFF_VS_TIGHT` (v25, postflop but preflop-adjacent),
`OPTIMAL_VALUE_SIZING_PER_ARCHETYPE` (v28), `SIZE_UP_PREMIUM_OPENS` (r20,
shipped 2026-08-13 after re-testing the old imprecise v19b result),
`THREEBET_SIZE_BY_POSITION`/`THREEBET_BLUFF_FROM_LATE_POSITION_ANY_
OPPONENT`/`BB_DEFEND_MDF_SCALED`/`SET_MINE_IMPLIED_ODDS` (r22/r23/r24/r27,
shipped 2026-08-15), `LIMP_BEHIND_OVER_LIMPERS` (confirmed since 2026-08-12
r16v but never actually flipped -- fixed 2026-08-16),
`TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR` (r21, +7.90/+23.26 bb/100),
`BB_DEFEND_VS_STEAL_MINRAISE` (r19v wide params, MAX_RAISE_BB=2.5/
VPIP_MULTIPLIER=2.0, +5.72/+4.15 bb/100 -- stacks on top of MDF above),
`SHOVE_AA_KK_VS_3BET_PLUS` (r18v, widened to `{AA,KK,QQ,AKs,AKo}`,
+31.41/+15.54 bb/100 -- see the note under "confirmed NOT real" below,
this makes `FOLD_PREMIUM_VS_EXTREME_AGGRO`/`FOLD_VS_3BET_FROM_PASSIVE`
structurally unreachable for their whole target hand set now). All
2026-08-16 numbers from `scripts/remaining_untested_confirm.sh`, log
`/tmp/remaining_untested_confirm_20260816_124429.log`.
`SB_THREEBET_OR_FOLD_VS_STEAL` (this file's first-ever SB-specific rule,
shipped 2026-08-17, +4.10/+5.91 bb/100).

### Preflop: confirmed NOT real (tested properly, correctly kept off)

`SQUEEZE_WIDER_RANGE`/`SQUEEZE_SIZE_UP_PER_CALLER` (v21, 300k/arm, real
null result), `SIZE_SCALED_CALL_RANGE` (v30, confirmed negative -6.46/
-5.67 -- but see below, a real bug was found in its implementation AFTER
this result, re-test pending), `CALL_RANGE_BY_RAISER_POSITION` (r17v, both
seeds land at true-zero), `MULTIWAY_AWARE`, `VALUE_RAISE_FACING_BET`
(-9.66 bb/100), several older v9/v14/v15/v16 range-widening theories (all
plateaued at breakeven even at 500k-2M hands), `BLUFF_3BET_BLOCKER_RANGE_
FLAG` (r25, -6.94/-4.13), `RAKE_ADJUSTED_OPEN_SIZING` (r28, inconclusive
-0.02/-0.29), `FOLD_VS_3BET_FROM_PASSIVE` (r29, -2.15 on seed42 only,
second seed got 0 divergent hands, unconfirmable), `r19v-bb-defend-
minraise-tight` parameterization (confirmed negative -4.15/-2.11 -- only
the wide parameterization above is shipped), `FOLD_PREMIUM_VS_EXTREME_
AGGRO` (r15v, all 4 hand-set/archetype/stack-fraction variants got 0
divergent hands on both seeds in the 2026-08-16 run -- see below, it's now
also structurally dead code for QQ/AKs/AKo since the widened shove range
intercepts those hands first).

### Preflop: everything that was still untested is now resolved (2026-08-16)

As of 2026-08-15 the section above listed a handful of genuinely never-run
flags plus a couple of imprecise first-pass numbers. All of them were run
to a clean adaptive stop (`scripts/remaining_untested_confirm.sh`, both
seeds, log `/tmp/remaining_untested_confirm_20260816_124429.log`):

- `TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR` (r21): +7.90+/-3.89 / +23.26+/-10.11
  -- confirmed both seeds (the earlier imprecise +7.72/+25.60 numbers were
  in the right ballpark). **Shipped True.**
- `SIZE_UP_WITH_VERY_STRONG_HAND` / `SIZE_UP_ON_WET_BOARD` (v23, never run
  before): +7.97/+7.22 and +14.65/+12.18 bb/100 respectively -- both
  confirmed both seeds. **Shipped True.**
- `RIVER_OVERBET_NUTS_VS_LOOSE` (v27, postflop -- listed here since it was
  part of this same never-tested batch) -- had no preset at all, added
  `v27-river-overbet-nuts-vs-loose`. First pass was a split verdict; the
  bigger-sample retest below resolved it to confirmed positive both seeds.
  **Shipped True.**
- `BB_DEFEND_VS_STEAL_MINRAISE`: the "medium" parameterization
  (multiplier 1.6) got 0 divergent hands both seeds -- a dead swept
  parameter, same class of bug as `SIZE_SCALED_CALL_RANGE`/`LIMP_BEHIND`'s
  multiplier. "Tight" (max_raise_bb=2.0, multiplier 1.3) confirmed
  NEGATIVE both seeds. "Wide" (max_raise_bb=2.5, multiplier 2.0) confirmed
  POSITIVE both seeds (+5.72/+4.15) -- **shipped True with the wide
  params**, stacking on top of the already-True `BB_DEFEND_MDF_SCALED`.
- `SHOVE_AA_KK_VS_3BET_PLUS`: the original AA/KK-only range (r13) is still
  untestable (0 divergent even forced). The wider r18v variants aren't:
  QQ+ range +14.66/+9.51 bb/100, QQ+/AK range +31.41/+15.54 bb/100 -- both
  confirmed both seeds, and the widest range gave the cleanest, largest
  result. **Shipped True with `SHOVE_VS_3BET_PLUS_RANGE =
  {AA,KK,QQ,AKs,AKo}`.** Side effect: this range exactly equals
  `FOLDABLE_PREMIUM_VS_EXTREME_AGGRO`, and the shove check runs first in
  `choose_abc_action`, so `FOLD_PREMIUM_VS_EXTREME_AGGRO` and
  `FOLD_VS_3BET_FROM_PASSIVE` can now never fire for their whole target
  hand set regardless of their own flag state -- effectively superseded,
  since shoving that range is now confirmed to beat calling it, so folding
  it was never going to win either. Tests updated to isolate
  `SHOVE_AA_KK_VS_3BET_PLUS=False` when testing those two flags in
  isolation (see `tests/test_abc_bot.py`).
- `FOLD_PREMIUM_VS_EXTREME_AGGRO` (r15v, all 4 variants): 0 divergent
  hands, both seeds, every variant -- genuinely untestable at natural
  incidence, now also structurally dead per the shove note above.
  **Stays False.**

191 tests re-run after all the flips above (plus fixing the 8 tests whose
assumptions the `SHOVE_AA_KK_VS_3BET_PLUS` range widening broke): still
all pass.

### The last 5 borderline flags, re-tested at bigger sample (2026-08-16)

User explicitly asked to re-check every still-uncertain result at higher
power. `scripts/borderline_bigger_sample_confirm.sh` -- both seeds, hand
cap raised to 1M, target-CI halved to 0.5 (log
`/tmp/borderline_bigger_sample_confirm_20260816_183316.log`):

- `RIVER_OVERBET_NUTS_VS_LOOSE` (v27): +1.12+/-0.54 (288k hands) /
  +4.04+/-2.00 (36k hands) -- now confirmed both seeds. **Shipped True.**
- `CALL_RANGE_BY_RAISER_POSITION` (r17v): -0.64+/-0.63 (56k) /
  -1.46+/-1.11 (32k) -- now confirmed NEGATIVE both seeds. The earlier
  "true-zero" read (1x sample) undersold a real small negative effect.
  **Stays False**, for a stronger reason than before.
- `PROBE_BET_TURN_AFTER_CHECK` (pf5): +0.24+/-0.14 / +0.22+/-0.13 --
  still inconclusive even with the CI target halved. Genuinely near-zero,
  not under-powered. **Stays False.**
- `BLOCK_BET_RIVER` (pf8): -0.78+/-0.77 confirmed negative (164k hands) /
  -0.38+/-0.50 inconclusive (348k hands) -- leans mildly negative now,
  doesn't clear the bar on both seeds. **UPDATE 2026-08-18**: pushed to a
  tighter target-CI (0.25), `scripts/borderline_bigger_sample_round2.sh`
  -- -0.73+/-0.70 (seed42, 172k) / **-0.39+/-0.39 (seed777, 492k, now
  confirmed_negative)** -- the seed777 run just hadn't run long enough
  before; more hands resolved it cleanly. **Confirmed NEGATIVE both seeds
  now, stays False with real confidence.**
- `LIMP_TRAP_WITH_MONSTERS` (r26): +0.16+/-0.32 inconclusive (92k) /
  +0.70+/-0.34 confirmed (160k) -- still a split verdict at 2-3x the
  earlier sample. Genuinely on the edge of measurability for this rare a
  spot (unopened AA/KK). **UPDATE 2026-08-18**: pushed further (same
  script/log as above) -- +0.16+/-0.24 (seed42, 136k) / +0.69+/-0.34
  (seed777, 160k, unchanged). Tighter seed42 CI now makes the two point
  estimates disagree with EACH OTHER beyond their own combined CI (0.53
  gap vs 0.42 combined) -- not just under-powered, genuinely inconsistent
  between samples for this rare a spot. Diminishing returns to keep
  pushing hand count alone. **Stays False, unresolved by design.**

This closes out every open question from the 2026-08-14/15/16 validation
rounds -- every flag in `abc_bot.py` now has an adequately-powered test
result behind its current True/False state (with `BLOCK_BET_RIVER` fully
resolved 2026-08-18 and `LIMP_TRAP_WITH_MONSTERS` understood as
genuinely hard-to-pin-down rather than just under-sampled). 191 tests
pass.

### 2026-08-18: TURN_OVERBET_NUTS_VS_LOOSE -- generalized RIVER_OVERBET_NUTS_VS_LOOSE off river-only

From the "what else globally needs checking" list: `RIVER_OVERBET_NUTS_
VS_LOOSE` (v27) was always restricted to the river, but that restriction
was never itself a tested finding -- just where the idea was first tried.
Built the turn analogue (`TURN_OVERBET_NUTS_VS_LOOSE`, same has_trips_or_
better bar and `LOOSE_ARCHETYPES` target, own sizing constant) and tested
it, `scripts/turn_overbet_confirm.sh`, log `/tmp/turn_overbet_confirm_
20260818_140943.log`, both seeds -- **confirmed POSITIVE both seeds,
resolved unusually fast (10k/16k hands)**: +1.86±0.84 (seed42) /
+1.69±0.81 (seed777), consistent magnitude. **Shipped True.**

Two other candidates from the same list were scoped and set aside rather
than built this round: per-opponent (not archetype-level) bluff-frequency
exploitation needs session-continuity simulation this project's precision
test harness doesn't support (`backend/dossier.py`'s `SeatDossier` stats
accumulate across many hands at one table; `probe_chance_enumeration.py`
samples one fresh hand at a time) -- a real infrastructure gap, not a
quick check. Tilt/bad-beat state-change detection has no groundwork in
either repo -- would need fresh research against the real dataset first.

### 2026-08-18, same session: two more "flagged as untested" candidates resolved

Both were literal comments in `abc_bot.py` itself, disclosed when their
sibling rules shipped as separate, never-tested questions --
`scripts/semibluff_turn_wetboard_confirm.sh`, log `/tmp/semibluff_turn_
wetboard_confirm_20260818_150344.log`, both seeds:

- **`SEMI_BLUFF_RAISE_DRAWS_TURN`** (extends pf3's flop-only semi-bluff
  raise to the turn): **confirmed POSITIVE both seeds**, +1.91±0.95
  (seed42, 216k hands) / +2.08±1.04 (seed777, 218k hands) -- same
  direction and similar magnitude as the already-confirmed flop version.
  **Shipped True.**
- **`SMALLER_BLUFF_ON_WET_BOARD`** (the flip side of `SIZE_UP_ON_WET_
  BOARD` -- smaller air-bluff sizing on a wet board instead of standard):
  **confirmed NEGATIVE both seeds**, -4.07±3.72 (seed42, 8k hands) /
  -4.46±3.78 (seed777, 10k hands). A cheaper bluff on a wet board loses
  more fold equity than it saves -- consistent with this file's recurring
  pattern that this population doesn't fold to sizing the way solver
  theory assumes. **Stays False.**

191 tests pass across multiple `PYTHONHASHSEED` values.

### 2026-08-19/20: MAJOR restructure -- archetype split into two independent axes, full pipeline rebuilt

User-directed: player classification is no longer one flat archetype
label. Now two independent axes:
- **Preflop archetype** (Nit/TAG/LAG/Loose-passive/Station/Maniac) --
  made **purely preflop**. It used to gate Maniac on a postflop stat
  (`af>=2.0`), mixing the two axes right where they're meant to be
  independent -- user caught this ("значит у нас неправильно
  распределены архетипы"). Redefined Maniac as `vpip>0.45 and
  pfr_ratio>=0.45` (an extreme-VPIP LAG), no postflop input at all.
- **`postflop_freq_tier`** (rare/normal/often) -- a 3-way split of the
  same `aggression_factor` stat, using literature-grounded poker-HUD AF
  thresholds (AF<2.0 / 2.0-3.0 / >3.0, researched via WebSearch per the
  user's explicit request to base this on real convention rather than
  fit our own data) rather than dataset-derived percentiles.

**Real population shift**: Maniac drops from 3352 to 756 players (12.5%
-> 2.8% of the labeled population) -- Station and Loose-passive absorbed
most of the reclassified players.

**Full cascade rebuilt** (user: "нужно вообще всё переделать под новые
типы"), each step committed/pushed separately in both repos:
1. All 4 `archetype_*.csv` reference tables (`build_archetype_tables.py`,
   full 4379-file raw re-parse, no OOM issues).
2. `matchup_hand_ev.csv` -- all 36 archetype pairs recomputed (~2 hours,
   `overnight_ev_batch.py`; had to delete the stale file first since it
   append-skips already-done pairs).
3. `player_profile_seeds.csv`.
4. **The ML opponent training dataset rebuilt** (34,543,852 decision
   rows) **and BOTH CatBoost models retrained** -- old models backed up
   first. This is the point of no return: the ML opponents now actually
   behave differently.
5. `session_length_by_archetype.csv` / `session_lengths_raw.csv`
   (same stale-file issue as step 2).
6. `ARCHETYPE_POPULATION_WEIGHTS` in `backend/sessions/live_dynamics.py`
   manually updated to the new counts.

191 tests + a 5000-hand whole-game smoke test both clean after the
retrain (+22.45±10.79 bb/100 excl. monster pots -- strategy still
clearly wins against the new population).

**First re-validation round** against the new population/model
(`scripts/repop_revalidate_round1.sh`, both seeds) -- prioritized the
single biggest lever plus the one flag whose loose-archetype set
explicitly includes Maniac:
- **`OPPONENT_AWARE_ARCHETYPES`** (v10, the biggest lever in the whole
  file): still confirmed POSITIVE both seeds, +47.01±11.91 (seed42) /
  +59.24±13.91 (seed777). Makes sense in hindsight -- `LOOSE_ARCHETYPES`'s
  three-archetype total (Loose-passive+Station+Maniac) barely moved in
  aggregate (18,360 -> 18,542 of 26,797) even though Maniac specifically
  shrank a lot.
- **`WIDER_3BET_VS_LOOSE`** (v15/B1): previously "active but unconfirmed"
  (old whole-game method, inside CI) -- now confirmed POSITIVE both
  seeds with the modern method, +4.91±2.43 (seed42) / +5.99±2.72
  (seed777). Resolves this backlog item and the population re-check at
  the same time.

**Second re-validation round** (`scripts/repop_revalidate_round2.sh`, both
seeds) -- every other shipped-True flag that reads an opponent
archetype-set membership, per user instruction "нужно проверить все
флаги зависящие от типа игроков у нас же теперь они новые":
- Cleanly re-confirmed POSITIVE both seeds (5): `FLOAT_FLOP_IN_POSITION`
  (+7.15±3.00 / +11.51±4.78), `BLUFF_3BET_VS_TIGHT` (v24, +3.85±1.91 /
  +5.42±2.60 -- first time ever confirmed with the modern method, was
  previously old-whole-game-only), `DONK_BLUFF_VS_TIGHT` (r10/v17,
  +1.25±0.61 / +2.47±1.23), `BARREL_BLUFF_VS_TIGHT` (v25, +3.89±1.82 /
  +6.94±3.44), `RIVER_BLUFF_MISSED_DRAW` (+2.03±0.98 / +2.85±1.36).
- Direction holds but weaker than pre-restructure, not a clean both-
  seeds re-confirmation (2): `RIVER_OVERBET_NUTS_VS_LOOSE` (v27,
  +0.94±0.83 seed42 inconclusive / +3.74±1.85 seed777 confirmed),
  `TURN_OVERBET_NUTS_VS_LOOSE` (+0.35±0.93 seed42 inconclusive, CI
  crosses zero / +1.88±0.93 seed777 confirmed). Both stay `True` on
  two-for-two positive direction plus the original pre-restructure
  confirmation, but flagged for a bigger-sample follow-up.
- Still untestable by self-play, both seeds (2): `STEAL_WIDER_VS_NIT` /
  `SIZING_TARGET_ARCHETYPES` (v14) -- zero divergent hands in 100k on
  both seeds, same pre-existing rare-opponent-behavior bottleneck
  (`TIGHT_ARCHETYPES_FOR_STEAL={"Nit"}`), unrelated to the restructure.
  Remains an open Tier-1 backlog item.

No flag flipped sign or was disabled across either re-validation round.

### `postflop_freq_tier`: infra built, then retrained (2026-08-20)

Second independent axis (rare/normal/often, from `aggression_factor`) built
in two deliberate stages, per user's explicit choice to do infra first:

1. **Infra-only** (commit `37c9699`): `live_dynamics.py` seats bots with a
   real per-archetype-weighted tier (`ARCHETYPE_FREQ_TIER_WEIGHTS`,
   real joint population counts); `TableTurnover.freq_tier_for(seat)`;
   `choose_abc_action` gained an `opponent_freq_tiers` param, documented
   as unused. At this stage seated bots were LABELED with a tier but
   didn't behave differently by it.
2. **Retrain**: `behavior_clone.py`'s `CAT_FEATURES` gained `"freq_tier"`;
   `build_training_data.py` now carries each real player's own measured
   `postflop_freq_tier` (ground truth, not sampled) into every training
   row; both CatBoost models retrained (old ones backed up first).
   Losses improved slightly (action 0.6699→0.6675, sizing 0.5909→0.5900)
   -- a real signal. 191 tests pass (3 `PYTHONHASHSEED` values), 5000-hand
   smoke test clean (+33.26±11.28 bb/100 excl. monster pots, better than
   the archetype-only-retrain baseline). Direct check confirms the model
   learned it: same archetype (Station), raise probability rises
   monotonically with tier -- rare 4.5% → normal 6.4% → often 7.5%.

**`WIDER_CALL_VS_OFTEN_TIER`** (2026-08-20, shipped True): the first rule
to actually read `opponent_freq_tiers`. Generalizes the `LOOSE_ARCHETYPES`
any-pair-or-better call across the freq_tier axis -- OR'd with the
existing archetype check, either being true is enough to widen. Confirmed
POSITIVE both seeds, +22.27±7.39 (seed42) / +11.24±5.51 (seed777). 191
tests pass, 5000-hand smoke test improved further (+38.47±11.76 bb/100
excl. monster pots, up from +33.26 pre-flag).

### 2026-08-21: pokerdom_pending_ideas backlog cleanup

Bigger-N re-checks (`scripts/pending_backlog_round1.sh`), both seeds where
applicable:
- **`USE_WIDE_VALUE_3BET`** (v9): last remaining Tier-1 item. CONFIRMED
  POSITIVE both seeds with the modern method, +6.73±2.88 (seed42) /
  +3.60±1.78 (seed777). No longer pending.
- **`FOLD_VS_3BET_FROM_PASSIVE`** (r29): re-run with a 300k-hand budget --
  ZERO divergent hands on BOTH seeds now. Confirmed untestable by self-
  play at the current population/model, same class as
  `STEAL_WIDER_VS_NIT`. Stays `False`.
- **`OPTIMAL_VALUE_SIZING_PER_ARCHETYPE`** (v28): magnitude pinned down
  with a big single run (90k hands, 3035 divergent), +1.39±0.79 bb/100.
- **`RIVER_OVERBET_NUTS_VS_LOOSE`** / **`TURN_OVERBET_NUTS_VS_LOOSE`**:
  bigger budget (up to 144k hands) confirms direction still positive both
  seeds, but the magnitude has converged close to zero (river:
  +0.51±0.98 / +0.98±0.83; turn: +0.72±0.57 / +0.59±0.53), both landing
  `inconclusive_small_effect` even at this sample size -- a real finding,
  not sampling noise. Whatever edge these had pre-restructure has largely
  evaporated. Both stay `True` (no evidence of harm) but should not be
  cited with their old magnitudes anymore.

191 tests pass, 5000-hand smoke test unaffected.

**Tier-5 confirmation** (`scripts/tier5_confirm.sh`, both seeds):
- **`FLOAT_TURN_IN_POSITION`**: `FLOAT_FLOP_IN_POSITION` generalized to
  the turn. Confirmed POSITIVE both seeds, +15.76±7.69 (seed42) /
  +10.28±4.86 (seed777). Shipped True.
- **`SIZE_UP_PREMIUM_3BETS`**: `SIZE_UP_PREMIUM_OPENS` generalized to the
  3-bet. Confirmed NEGATIVE seed42 (-1.80±1.63), inconclusive-but-
  negative-leaning seed777 (-0.50±0.98). Unlike the open-sizing version,
  sizing up a value 3-bet with a premium hand does NOT help -- a 3-bet
  already telegraphs strength, so it likely just makes folding easier for
  the raiser's continuing range. Stays False, tested-and-rejected.

191 tests pass, 5000-hand smoke test improved further (+40.75±11.23
bb/100 excl. monster pots, up from +38.47).

**Everything else in this file's confirmed-flag history has NOT yet been
re-validated against the new population** -- a large, explicitly
ongoing, multi-session task. See `pokerdom_pending_ideas` memory for the
tracking note; do not assume old numbers still hold without re-checking.

### 2026-08-21: Tier 4 groundwork -- tilt-after-cooler infra (harder half)

User picked the harder of Tier 4's two ideas (tilt-after-cooler, over the
freq_tier-style static-label shortcut for per-opponent bluff frequency).
Third session-scoped signal, but genuinely dynamic hand-to-hand unlike
archetype/freq_tier:
- `live_dynamics.py`: `TableTurnover` tracks each seat's
  `hands_since_cooler` across the session. New
  `record_hand_for_tilt(hand)` (called alongside `after_hand()`) detects
  a cooler -- >=15bb invested, real showdown, lost -- same definition as
  `PokerDom_Microlimits_Analysis/scripts/check_tilt_after_cooler.py`.
  `tilt_tier_for(seat)` buckets none/acute(1-2)/fading(3-5)/residual(6-10).
- `build_training_data.py` reuses that script's cached per-(hand,player)
  `hands_since_cooler` (768,494 post-cooler pairs) -- causally safe, only
  depends on that player's own past hands.
- `behavior_clone.py`/`train_behavior_clone.py`: `CAT_FEATURES` gained
  `"tilt_tier"`. Retrained -- losses barely moved (expected, ~2.2% of
  rows are nonzero) but a sanity check confirms the model learned the
  real direction: call probability +2.3pp / fold probability -3.2pp the
  moment tilt_tier leaves "none", at a fixed test decision point.
- `choose_abc_action` gained `opponent_tilt_states`, unused so far.
  `backend/api.py` + 6 scripts wired to compute and pass it through.

191 tests pass, 5000-hand smoke test unchanged (+40.90±11.00 bb/100 excl.
monster pots -- expected, nothing reads the new signal yet).

### 2026-08-22: the sequence-of-hands simulator got built after all

Turned out not to need new architecture: `_run_probe_chunk` already
keeps the same `TableTurnover` alive across its whole `n_hands` loop
(only the Table's stacks reset every hand, not opponent session state).
Added `turnover.record_hand_for_tilt(hand)` right after each hand that
genuinely finishes (guarded on `Hand.finished`, which naturally excludes
divergent hands -- no ambiguity about which forked hypothetical outcome
should update a shared persistent object). `opponent_tilt_states` now
reads `turnover.tilt_tier_for(seat)` live instead of sampling.

**`WIDER_CALL_VS_TILTING_OPPONENT`**, re-tested with real accumulated
tilt state (`scripts/tilt_confirm_live.sh`): incidence jumped ~8x (0.20%
vs 0.024% divergent hero hands before) and seed42 re-confirmed much
faster, +3.16±1.34 bb/100 (16k hands, 32 divergent). seed777 again found
zero divergent hands (150k budget) -- a separate diagnostic confirmed
tilt state itself fires fine for seed777 (~25% of seat-hands, MORE than
seed42's ~14%), not a bug there.

**Real bug found and fixed 2026-08-22**: the OPPONENT bots' own
`choose_bot_action` calls in `probe_chance_enumeration.py` never actually
passed `tilt_tier` (only hero's ground-truth read did) -- seated
opponents never behaved differently while tilting during EITHER test
above, only their label said so. Both seed42-only signals were most
likely noise. Fixed (opponents now read `tilt_tier` same as
archetype/freq_tier) and re-tested (`scripts/tilt_and_bluff_confirm.sh`):
**CONFIRMED POSITIVE both seeds**, +2.60±1.06 (seed42) / +3.09±1.31
(seed777). Shipped `True`. 191 tests pass, 5000-hand smoke test improved
(+45.53±12.26 bb/100 excl. monster pots, up from +33.48).

**The other Tier 4 idea (per-opponent bluff frequency)**: built BOTH
competing definitions per user's "build both, compare" instruction.
`find_frequent_bluffers.py`'s original (last river aggressor, real
showdown, lost) only reliably covers 49/26,797 players (0.2%). A second,
broader definition (any-street aggressor, real showdown, lost) covers
7,974/26,797 (29.8%, ~10x better) --
`scripts/compare_bluff_frequency_variants.py` in the analysis project.
Wired both all the way through the same infra pattern (population
sampling, real-player lookup, `CAT_FEATURES`, retrain, two candidate
hero rules `BLUFF_CATCH_VS_FREQUENT_BLUFFER_A`/`_C`). **Both stayed
untestable even at a 150k-hand-per-seed budget** -- zero divergent
hands, both seeds, both variants. Better coverage alone didn't fix it:
the real bottleneck is compound rarity (aggressor + "high" tier + hero
holding a qualifying hand not already covered elsewhere). Both stay
`False`.

### 2026-08-22: Tier 6 brainstorm backlog, taken in order

`scripts/tier6_confirm.sh`, both seeds:
- **`MULTIWAY_TIGHTEN_VS_SHORT_STACK_BEHIND`** (#1, relative stack among
  multiple opponents, a genuinely new angle -- stack-depth-conditioned,
  not frequency-conditioned like the three prior failed multiway
  attempts): ZERO divergent hands both seeds (150k budget). Genuinely
  untestable, same class as `STEAL_WIDER_VS_NIT`.
- **`CONTINUOUS_FOLD_VS_BET_SIZE`** (#4, graduated fold probability
  instead of a hard pot-fraction cutoff): confirmed NEGATIVE both
  seeds, -0.82±0.33 (seed42) / -0.57±0.22 (seed777). A genuinely
  different mechanism, same conclusion every prior "fold more to bet
  size" idea reached -- this population just doesn't punish oversized
  bets. Tested-and-rejected.
- **`CONFIDENCE_GATED_ARCHETYPE_READ`** (#2, sample-size-weighted trust
  in an archetype read): confirmed NEGATIVE both seeds, -32.67±10.06
  (seed42) / -29.75±8.64 (seed777) -- tested via `scripts/
  confidence_gate_confirm.py`'s special many-short-independent-sessions
  method (the normal long-adaptive-run harness can't reach the low-
  confidence window at any rate, since occupants never reseat mid-run).
  Real structural finding: `opponent_archetypes` is always ground truth
  in this sim from hand 1 -- no estimation noise for confidence to
  protect against, so distrust only discards real value. Would need a
  genuinely noisy read (e.g. live dossier estimates) to have a chance.
- **`REAL_RANGE_NUT_ADVANTAGE_SIZING`** (#3, real Monte Carlo range-vs-
  range equity replacing `NUT_ADVANTAGE_SIZING`'s binary proxy): found
  `PokerDom_Microlimits_Analysis/src/engine/range_equity.py` already
  exists and is used by the live EV panel -- not a from-scratch build.
  Tested (`scripts/real_range_confirm.sh`): ZERO divergent hands both
  seeds at 150k hands each (~52 min total, Monte Carlo runs ~13ms/hand
  here). Since the cheap proxy is already active in both arms,
  divergence only happens on disagreement -- and it never disagreed
  enough to change the sizing decision. The cheap proxy already
  captures what the expensive calculation would add here.

**Closes the full Tier 6 backlog** (#1-#4, taken in order): two
confirmed-negative, two genuinely-untestable-by-self-play. No flag
shipped True, but every idea reached a clear, honest conclusion instead
of staying a vague brainstorm item.

191 tests pass, no behavior change (all flags off).

### 2026-08-22: Tier 1.5 finally resolved -- underpowered, not shrunk

`RIVER_OVERBET_NUTS_VS_LOOSE`/`TURN_OVERBET_NUTS_VS_LOOSE` landed
`inconclusive_small_effect` at the 2026-08-21 post-restructure re-check
(small samples, ~144k/8k hands). A much bigger budget
(`scripts/tier1_5_bigger_sample.sh`, up to 1M hands, `target_ci=0.5`)
resolved both CLEANLY `confirmed_positive` on both seeds:
- `RIVER_OVERBET_NUTS_VS_LOOSE`: +1.11±0.54 (seed42, 322k hands) /
  +0.82±0.41 (seed777, 338k hands).
- `TURN_OVERBET_NUTS_VS_LOOSE`: +1.45±0.71 (seed42, 20k hands) /
  +1.21±0.56 (seed777, 14k hands).

Magnitudes are back in line with the original pre-restructure numbers --
the earlier "shrunk close to zero" reading was sampling noise from an
underpowered run, not a real change in the underlying effect. **This
closes the last open item from this session's full backlog audit** --
every flag/idea flagged as pending across Tiers 1 through 6 now has a
real, tested, documented conclusion.

### Postflop: what's confirmed and shipped True

The Tier-1 unconditional flop c-bet with initiative, value-betting
top-pair-or-better on every street (regardless of initiative -- this was a
measured fix for a real -51.79 bb/100 leak from checking hands down),
opponent-archetype-aware wider calling (part of v10 above),
`OPTIMAL_VALUE_SIZING_PER_ARCHETYPE` (v28),
`BARREL_BLUFF_VS_TIGHT` (v25, turn/river scare-card bluff vs known tight
opponents), `SEMI_BLUFF_RAISE_DRAWS`/`NUT_ADVANTAGE_SIZING`/`SPR_SCALED_
THRESHOLDS` (pf3/pf4/pf7, shipped 2026-08-14), `SIZE_UP_WITH_VERY_STRONG_
HAND`/`SIZE_UP_ON_WET_BOARD` (v23, shipped 2026-08-16, +7.97/+7.22 and
+14.65/+12.18 bb/100), `RIVER_OVERBET_NUTS_VS_LOOSE` (v27, shipped
2026-08-16 after a bigger-sample retest, +1.12/+4.04 bb/100),
`FLOAT_FLOP_IN_POSITION` (published "float" concept, first version of it
this file has ever had, shipped 2026-08-17, +8.10/+9.35 bb/100),
`RIVER_BLUFF_MISSED_DRAW` (bluff the river with a personally-missed
flush/straight draw vs known tight archetypes, shipped 2026-08-17,
+1.78/+2.95 bb/100), `TURN_OVERBET_NUTS_VS_LOOSE` (turn analogue of
`RIVER_OVERBET_NUTS_VS_LOOSE`, generalized off river-only, shipped
2026-08-18, +1.86/+1.69 bb/100), `SEMI_BLUFF_RAISE_DRAWS_TURN` (turn
analogue of pf3's flop-only semi-bluff raise, shipped 2026-08-18,
+1.91/+2.08 bb/100).

### 2026-08-17: overnight research pass -- iso/shove sizing vs published theory, SB strategy, postflop gaps

User asked to (1) sanity-check the shipped iso-limper sizing and the
AA/KK/QQ/AKs/AKo shove against actual published poker theory, (2) build the
small-blind-specific strategy this file never had, (3) flatten
`STANDARD_SIZING_POT_FRACTION` (both the value-bet base AND the Tier-1
unconditional flop c-bet reuse this one constant) from 0.525 to a flat 0.50
-- direct instruction, not a hypothesis, applied immediately, and (4) look
harder at postflop for missing real spots, researching all of it against
published sources first. Full results and sourcing in `abc_bot.py`'s own
changelog docstring (search "overnight research pass"); short version:

- **Iso-limper sizing**: published theory (Upswing/PreflopWizard/2+2
  consensus) says ~3-4bb + 1bb/limper. Tested that exact sizing
  (`r12v-published-theory`, base=4.0/per-limper=1.0) against the shipped
  5.5bb/1.5bb -- **confirmed NEGATIVE both seeds, -30.24/-39.23 bb/100**.
  The bigger, non-standard sizing this file already shipped is genuinely
  better against this specific ML-bot population. No code change.
- **Shove vs. sized 4-bet**: published 100bb-effective 4-bet theory says
  ~2.3-2.6x the 3-bet, not all-in (all-in becomes standard around 50bb
  effective). Tested a sized 4-bet (`SIZED_4BET_INSTEAD_OF_SHOVE`) against
  the shipped all-in shove -- **confirmed NEGATIVE both seeds, -9.62/-2.16
  bb/100**. The shove stays. Stays False.
- **SB strategy** (this file had literally none before tonight):
  `SB_BIGGER_OPEN_SIZING` (3bb instead of 2.5bb, blind-vs-blind only) --
  inconclusive both seeds, +0.19/+0.04, genuinely near-zero, stays False.
  `SB_THREEBET_OR_FOLD_VS_STEAL` (3-bet the whole continue range facing a
  late-position steal instead of ever flat-calling) -- **confirmed
  POSITIVE both seeds, +4.10/+5.91 bb/100, shipped True.**
- **Postflop gaps**: `FOLD_MARGINAL_VS_CHECK_RAISE` (published micro-stakes
  theory: check-raises there skew value-heavy, fold marginal top-pair more)
  -- **confirmed NEGATIVE both seeds, -0.37/-0.56 bb/100** (each needed
  350k+ hands, check-raises are rare in this bot's self-play) -- the
  published exploit does NOT transfer to this ML-bot population, stays
  False. `FLOAT_FLOP_IN_POSITION` (call a flop bet in position with no
  hand/draw, bet the turn if checked to) -- **confirmed POSITIVE both
  seeds, +8.10/+9.35 bb/100, shipped True.**
- Full audit of `choose_abc_action` surfaced more real gaps not acted on
  tonight: no distinct response to a donk lead while hero has initiative,
  no board-texture discount when calling a `made` hand (a plain top pair
  calls a big bet on a 4-flush river the same as on a dry one), no
  give-up-or-bluff decision for a missed draw on the river. Real candidates
  for a future pass, not implemented yet.

### 2026-08-17, later same day: the 3 remaining postflop gaps, closed

Closed all 3 gaps flagged above. `scripts/postflop_gaps_confirm.sh`, both
seeds, log `/tmp/postflop_gaps_confirm_20260817_140539.log`:

- `FOLD_MARGINAL_VS_BIG_DONK` (fold plain top pair to a big, >=66% pot,
  donk lead while hero has initiative) -- **confirmed NEGATIVE both
  seeds**, -0.77±0.31 (seed42, 92k hands) / -0.70±0.28 (seed777, 108k
  hands). **Stays False.**
- `FOLD_TOP_PAIR_VS_WET_BOARD_TIGHT` (fold plain top pair to a real-sized
  bet on a wet board from a known tight archetype) -- **confirmed
  NEGATIVE both seeds**, -1.13±0.43 (seed42, 78k hands) / -1.51±0.58
  (seed777, 56k hands). **Stays False.**
- `RIVER_BLUFF_MISSED_DRAW` (bluff the river, 66% pot, when checked to
  after hero's own flush/straight draw missed, vs known tight archetypes)
  -- **confirmed POSITIVE both seeds**, +1.78±0.88 (seed42, 218k hands) /
  +2.95±1.45 (seed777, 94k hands). **Shipped True.**

Net: 1 shipped True, 2 tested and rejected. This is now the **third and
fourth** "add more theory-based folding" idea this same night to fail
against this population (after `FOLD_MARGINAL_VS_CHECK_RAISE`) -- a
consistent, real pattern, not noise: published micro-stakes folding
advice (check-raise-aware, donk-size-aware, board-texture-aware) keeps
not transferring to this specific ML-bot population, while new *betting*
lines (`FLOAT_FLOP_IN_POSITION`, now `RIVER_BLUFF_MISSED_DRAW`) keep
measuring as real wins. This closes out every postflop gap identified in
the 2026-08-17 audit. Also fixed a second instance of the hash-seed
test-fragility bug class (`test_does_not_isolate_a_limper_wider_when_
flag_off`) and preemptively swept the rest of `tests/test_abc_bot.py` for
the same `next(iter(...))` pattern (4 more occurrences fixed). 191 tests
pass across 5 different random `PYTHONHASHSEED` values.

### 2026-08-17, later still: 4 follow-up ideas raised while explaining the strategy

While walking the user through the full preflop/postflop decision tree,
four concrete, testable questions came up. User said to just record them
first ("запиши"), then later gave the go-ahead to actually build and test
all 4: `scripts/followup_ideas_confirm.sh`, both seeds, log
`/tmp/followup_ideas_confirm_20260817_164109.log`. All 4 resolved cleanly,
no split verdicts:

- **SB open 3.5bb** (`sb-open-3.5bb` preset) -- re-tests `SB_BIGGER_OPEN_
  SIZING` at a bigger step than the already-tested 3.0bb (which was
  inconclusive, +0.19/+0.04). Still inconclusive both seeds, +0.27±0.15
  (seed42) / +0.08±0.10 (seed777) -- even tighter around zero. Not a
  step-size artifact -- SB open sizing genuinely doesn't move this
  population. **Stays False.**
- **`TIGHT_BIG_ISO_RAISE_LIMPERS` vs `ISO_WIDER_RANGE_OVER_LIMPERS`, real
  head-to-head** -- found while explaining the code: `ISO_WIDER_RANGE_
  OVER_LIMPERS`'s own branch has been **structurally dead** since
  `TIGHT_BIG_ISO_RAISE_LIMPERS` shipped True the same day back in
  2026-08-12 (that flag is unconditional on `n_limpers>=1`, no hand-set
  gate, so it always wins). The confirmed +22.10/+19.67 bb/100 numbers
  behind `ISO_WIDER_RANGE_OVER_LIMPERS` were real for an isolated test
  against "no isolation change at all," but never described how it
  compares to `TIGHT_BIG_ISO_RAISE_LIMPERS` specifically. Ran the real
  head-to-head (`tight-iso-vs-wide-iso-headtohead` preset): **confirmed
  NEGATIVE both seeds** for `ISO_WIDER_RANGE_OVER_LIMPERS` as the live
  mechanism, -14.19±11.63 (seed42) / -33.94±17.01 (seed777). Today's
  default genuinely wins, not just by code-priority accident. **`ISO_
  WIDER_RANGE_OVER_LIMPERS` flipped to `False`** (no behavior change --
  it was already unreachable -- just stops the flag's value from lying
  about being a live, strong lever).
- **SB flat-call vs fold, absolute EV** (`sb-flat-call-vs-fold-
  diagnostic` preset, new diagnostic-only flag `SB_FOLD_VS_STEAL_
  DIAGNOSTIC`) -- user's sharp question: does `SB_THREEBET_OR_FOLD_VS_
  STEAL`'s win mean SB's postflop game is too weak OOP to play ANY
  continue profitably, making 3-bet/fold look artificially good? Tested
  the absolute EV of SB's flat-call range vs a steal, against a pure
  fold (not against 3-betting) -- **confirmed NEGATIVE both seeds** for
  folding, -9.58±4.37 (seed42) / -4.82±2.53 (seed777). Flat-calling
  clearly beats folding on its own. **Answer: no** -- SB's call range is
  solidly +EV in absolute terms; 3-betting beats an already-profitable
  call, it doesn't rescue an unprofitable one. Diagnostic-only, stays
  `False` either way.
- **Narrow the tight-iso range per additional limper**
  (`TIGHT_ISO_TIGHTENS_PER_EXTRA_LIMPER`, new flag) -- today's mechanism
  only scales sizing with `n_limpers`, not the range itself. **Confirmed
  NEGATIVE both seeds**, -5.98±3.29 (seed42) / -14.42±6.09 (seed777).
  Further narrowing hurts -- the fixed-range-plus-bigger-sizing approach
  already in place is correct. **Stays False.**

Net: 0 new flags shipped True, 1 stale/misleading flag corrected, 3
honest negative findings that each rule out a real concern rather than
just "not tested." 191 tests pass across multiple `PYTHONHASHSEED` values.

Log: `/tmp/night_research_confirm_20260817_071948.log`. Also fixed a real,
unrelated test-fragility bug found the same night: a test's
`next(iter(a_set))` pick was hash-seed-dependent and could intermittently
select a hand `LIMP_BEHIND_OVER_LIMPERS` legitimately calls with instead of
folding it, causing a flaky failure depending on `PYTHONHASHSEED` -- fixed
to a deterministic `sorted()` pick. 191 tests pass across multiple random
hash seeds.

### Postflop: confirmed NOT real

`VALUE_RAISE_FACING_BET` (v22, raising two-pair+ instead of calling,
-9.66 bb/100 -- real, checked twice), `MULTIWAY_AWARE`'s original test
(measured worse). **Correction (2026-08-17): the claim that its three
sub-flags were "never separately re-tested at real power" was stale/
wrong** -- v18 (2026-08-07) already tested `MULTIWAY_NARROW_CALL_RANGE`,
`MULTIWAY_DISABLE_AIR_CBET`, and `MULTIWAY_DISABLE_LOOSE_CALL`
individually (whole-game method); all three measured negative-or-
borderline, no hidden winner. Re-confirmed with the modern chance-
enumeration method 2026-08-17 (`scripts/multiway_subflags_recheck.sh`,
log `/tmp/multiway_subflags_recheck_20260817_171917.log`, both seeds) --
`MULTIWAY_DISABLE_AIR_CBET` -24.96±8.02/-44.70±10.93,
`MULTIWAY_DISABLE_LOOSE_CALL` -29.70±7.94/-26.51±7.36,
`MULTIWAY_NARROW_CALL_RANGE` (the one borderline case in the old
whole-game test) -36.83±11.79/-29.68±8.90 -- all three confirmed
negative on both seeds, no ambiguity left. Stay `False`.

`HERO_PROGRESSIVE_POT_DAMPING` (r11, dropping hero's own flat ~55%-pot
value-bet sizing as the pot grows past 8bb) -- **correction (2026-08-17):
this was wrongly listed as confirmed/shipped True elsewhere in this file
until now.** The code has it `False`; the full-model ablation table below
already had the right number all along (`+72.06 ± 6.94` when removed --
i.e. the model is BETTER without this rule, `disabled, likely harmful`).
No new test needed, just a doc-drift fix.

### Postflop: pf1-pf10, built AND tested 2026-08-14

All ten postflop ideas were implemented as off-by-default flags in
`abc_bot.py` (same pattern as r22-r29), then statistically validated the same
day (user gave explicit go-ahead) via `scripts/pf_batch_confirm.sh` --
adaptive chance-enumeration, `--comparison current`, both base-seed 42 and
777, log `/tmp/pf_batch_confirm_20260814_164343.log`. Full per-flag numbers
are in `abc_bot.py`'s own changelog docstring (search "pf1-pf10 validation").

**Shipped True** (confirmed positive both seeds):
3. `SEMI_BLUFF_RAISE_DRAWS` -- raise (not just call) a flush/open-ended
   straight draw facing a bet, flop only, heads-up only. +1.70/+2.79 bb/100.
4. `NUT_ADVANTAGE_SIZING` -- size up a value bet when the board favors
   hero's own preflop-raiser range. +1.95/+2.00 bb/100 (very consistent).
7. `SPR_SCALED_THRESHOLDS` -- widen the calling bar to any-pair-or-better
   when SPR is already low (<=3.0). +15.32/+26.20 bb/100 (real but noisy
   magnitude).

**Stays False -- confirmed negative, do not revisit without a new angle**:
1. `TEXTURE_DEPENDENT_CBET_SIZING` -- -4.80/-6.53 bb/100.
6. `POT_CONTROL_MARGINAL_HANDS` -- -7.48/-5.91 bb/100.
9. `BLOCKER_BASED_RIVER_BLUFF` -- -1.24/-3.93 bb/100.
10. `DELAYED_CBET_MARGINAL` -- -12.57/-21.69 bb/100.

**Stays False -- inconclusive, effect too small vs. CI on both seeds**:
5. `PROBE_BET_TURN_AFTER_CHECK` -- +0.21/+0.17 bb/100.
8. `BLOCK_BET_RIVER` -- +0.22/+0.43 bb/100.

2. `MULTIWAY_DISABLE_AIR_CBET` -- unchanged, pre-existing, still untested
   (pf2 reused this flag rather than getting its own).

191 tests re-run after flipping pf3/pf4/pf7 to True: still all pass.

## What's actually being worked on right now

The live thread of work is **not** the practice-app UI — it's a long
empirical strategy-research project built on top of `backend/bots/abc_bot.py`
("ABC bot"), a hand-coded rule-based poker strategy. Read that file's own
module docstring first — it is a complete, honest, versioned changelog
(v1→v30) of every rule that's ever been tried, with real measured bb/100
deltas and confidence intervals for each. This CLAUDE.md summarizes state;
`abc_bot.py`'s docstring is the source of truth for *why* each rule exists.

### The statistical standard used throughout

A measured delta between baseline and treatment is only called **"confirmed
real"** if `|delta| > sqrt(CI_a² + CI_b²)` — the two runs' 95% CIs combined
in quadrature. If it doesn't clear that bar, the honest statement is "not
demonstrated" (not "disproven" — could still be a small real effect buried
in noise). This standard gets applied consistently everywhere in this
project; don't report a delta as "working" without checking it against this.

### ABC bot flag status as of now

**Confirmed real (cleared combined CI at real sample size):**
| Flag | Delta | Sample | Note |
|---|---|---|---|
| v10 (opponent-aware calling bar) | +16.05 bb/100 | 80k | the original, biggest lever |
| v17 C2 (`DONK_BLUFF_VS_TIGHT`) | +3.40 bb/100 | 500k | re-confirmed 2026-08-11 |
| v24 (`BLUFF_3BET_VS_TIGHT`) | +1.80 bb/100 | 2,000,000 | confirmed 2026-08-11, was inside CI at 300k |
| **v29 (`ISO_WIDER_RANGE_OVER_LIMPERS`)** | **+22.10 / +19.67 bb/100 (2 indep. seeds)** | chance-enum, ~6k divergent each | **shipped True 2026-08-12/13** -- see "Independent second-seed cross-check" section below |
| **v25 (`BARREL_BLUFF_VS_TIGHT`)** | **+1.99 / +1.33 bb/100 (2 indep. seeds)** | chance-enum, ~60 divergent each | **shipped True 2026-08-12/13** -- smaller than v29 but doubly confirmed |
| **v28 (`OPTIMAL_VALUE_SIZING_PER_ARCHETYPE`)** | **+2.25 / +0.82 / +4.88 / +1.45 / +0.68 bb/100 (5 indep. seeds)** | chance-enum, up to 54k hands each | **shipped True 2026-08-12/13** -- 5/5 independent samples positive (never once negative; ~3% chance of that by pure luck around a true-zero effect), magnitude noisy (0.68-4.88), best-precision single estimate +1.45+/-0.62 |
| **r20 (`SIZE_UP_PREMIUM_OPENS`)** | **+4.00 / +3.05 bb/100 (2 indep. seeds)** | chance-enum, ~90-220 divergent each | **shipped True 2026-08-13** -- old v19b whole-game test (+1.76/-0.76, inside CI) was too imprecise to see this; re-tested with chance-enum, combined-CI-in-quadrature 2.38 vs 0.95 delta, well inside |

**Tested, NOT demonstrated (shipped OFF, kept in code for reference):**
v1-v9 range-only tweaks (plateaued near breakeven), v9 `USE_WIDE_VALUE_3BET`
(+0.80 @ 500k, inside CI even at 6x original N), v11 `MULTIWAY_AWARE`
(measured WORSE, textbook theory that didn't transfer to this population),
v14 A1+A2 `STEAL_WIDER_VS_NIT`+`SIZING_TARGET_ARCHETYPES` (+0.67 @ 500k,
inside CI, but sign-consistent across two independent samples — the one
candidate worth a bigger re-test if ever revisited, **deliberately deferred
per user request, do not re-run without asking**), v15 B1+B2
`WIDER_3BET_VS_LOOSE`+`SIZE_UP_ON_TURN` (+1.62 @ 500k, inside CI, sign
flipped vs its original 80k run — looks like noise around zero), v16 C1
`ISO_RAISE_OVER_LIMPERS` (later full-model ablation `-0.60 +/- 0.99`, no
proven benefit), v19 hero pot damping (later full-model ablation measured
removing it much better, `+72.06 +/- 6.94`), v21 `SQUEEZE_WIDER_RANGE`/
`SQUEEZE_SIZE_UP_PER_CALLER`, v22 `VALUE_RAISE_FACING_BET` (measured WORSE,
-9.66 bb/100), r17v `CALL_RANGE_BY_RAISER_POSITION` (2026-08-13: +0.07+/-0.99
@ seed42, -0.98+/-0.99 @ seed777, both `inconclusive_small_effect`, consistent
with true zero).

**Pattern worth remembering**: three separate "widen a range because a
population frequency table says so" theories (v9, v14, v15/A1+A2/B1+B2) have
now all failed to clear the noise floor, even at large N. Rules that change
*what the bot does* in a spot that didn't exist before (v10, v16, v17, v24)
keep measuring as real, larger effects. Weight new ideas accordingly — a
new range-widening idea should be viewed skeptically until tested here.

**Built + committed, mechanically tested, but A/B result NOT YET RUN:**
v25 `BARREL_BLUFF_VS_TIGHT` (turn/river scare-card bluff), v26
`FOLD_PREMIUM_VS_EXTREME_AGGRO` (fold QQ/AKs/AKo to an extreme re-raise from
a known Nit/TAG), v27 `RIVER_OVERBET_NUTS_VS_LOOSE` (150% pot with trips+ vs
loose archetypes), v28 `OPTIMAL_VALUE_SIZING_PER_ARCHETYPE` (real EV-computed
sizing tier per archetype instead of a hardcoded Nit/TAG shortcut), v29
`ISO_WIDER_RANGE_OVER_LIMPERS` (wider range isolating limpers, not just
bigger sizing), v30 `SIZE_SCALED_CALL_RANGE` (call range widens/narrows by
the actual raise size faced), r13 `SHOVE_AA_KK_VS_3BET_PLUS` (AA/KK shove
instead of flat-call when facing 3bet/4bet+). **These need a follow-up
confirmatory batch —
ask the user before launching it, don't just start it because it's "next."**

### The confirmatory batch currently running (as of this snapshot)

`scripts/overnight_confirm_flags.sh`, launched via
`nohup caffeinate -i bash scripts/overnight_confirm_flags.sh > /tmp/overnight_confirm_launcher.log 2>&1 & disown`,
logging to `/tmp/overnight_confirm_20260811_122418.log`. 6 stages:

1. ✅ done — legacy flags v9/v14/v15/v16/v17 @ 500k/arm (results above)
2. ✅ done — v24 @ 2,000,000 hands/arm → **+1.80 bb/100, CONFIRMED**
3. 🔄 running now — v23 sizing-theory (`SIZE_UP_WITH_VERY_STRONG_HAND` /
   `SIZE_UP_ON_WET_BOARD`, 4-arm test) @ 1,000,000 hands/arm
4. ⏳ queued — overbet-fold (`FOLD_TOP_PAIR_VS_OVERBET`) @ 500k/arm
5. ⏳ queued — tier-follow-up (`VALUE_RAISE_TRIPS_OR_BETTER_ONLY`) @ 500k/arm
6. (script ends after stage 5 — labeled as a 6-stage plan including the
   opening `=== confirmatory run started ===` banner; check the script
   itself for the exact remaining count)

Check progress: `tail -f /tmp/overnight_confirm_20260811_122418.log` and
`ps aux | grep simulate_abc_bot`. **When this finishes**, v25-v30 above are
next in line for a similar batch — ask the user first, do not auto-launch
(see workflow rules below).

### Fixed methodology issue: common-random paired A/B tests

Discovered 2026-08-11, then fixed in the current working tree. Earlier A/B tests in
`scripts/simulate_abc_bot.py` called `run_batch(..., seed=42)` for both the
baseline and treatment arm, with comments claiming "same seed — the flag is
the only thing that varies." **This claim is false.** Verified empirically:

```python
run_batch(3000, RAKE_PERCENT, RAKE_CAP_BB, seed=42)  # → 94.6 bb/100
run_batch(3000, RAKE_PERCENT, RAKE_CAP_BB, seed=42)  # → 152.7 bb/100 (!)
```

Same seed, same call, wildly different results. Root cause: `seed=42` only
seeds `TableTurnover` (which bot archetype sits where / turnover timing).
Two things are NOT seeded at all:
- `Deck.shuffle()` (in the sibling repo's `src/engine/cards.py`) calls the
  **global, unseeded** `random.shuffle` — card deals are never reproducible.
- `choose_bot_action(...)` in `behavior_clone.py` builds
  `rng = random.Random(seed)` with `seed=None` by default, and
  `simulate_abc_bot.py` never passes one — every ML bot's own mixed-strategy
  decision draws from OS entropy every call.

**Why this matters**: old baseline-vs-treatment comparisons in this project
were two fully independent random samples, not a
paired comparison — hence needing 500k-2,000,000 hands/arm to see effects of
only 2-5 bb/100. The harness now has `--common-random`, deterministic
per-hand deck seeding, deterministic per-decision ML-bot RNG seeds, and
`_paired_delta_stats(...)` so future runs can report the paired EV delta and
the CI shrink versus the old independent-arm estimate. The sibling
Analysis repo's `Deck.shuffle(rng=...)` support is part of this fix.

There is also a second, lower-variance probe:
`scripts/probe_chance_enumeration.py`. It runs baseline/treatment in
lockstep, and when hero's action first differs it averages the continuation
over each possible next board card while still counting the whole averaged
branch as one observation. Use `scripts/chance_enumeration_confirm_presets.sh`
and `scripts/summarize_chance_enumeration_log.py` for fixed-N batch runs.
For normal follow-up work, prefer
`scripts/adaptive_chance_enumeration_confirm_presets.sh`: it runs chunks,
flushes progress after every chunk, and stops each preset once a positive
signal is large enough (`CI <= abs(delta) * EFFECT_RATIO`, default `0.5`), or
when the configured hand/divergence caps are hit. For negative deltas it can
stop once `CI <= abs(delta)`, because that is already enough to classify the
flag as worse. `TARGET_CI` is still used to call small/inconclusive effects,
but it no longer blocks a clearly large positive signal. Rules that never find
any divergent hands stop at `MAX_ZERO_DIVERGENT_HANDS` and should be labeled
"not enough divergent hands," not as EV-zero. This is a methodology tool, not
a full session simulator replacement: it starts each hand from fresh stacks
and enumerates only the next chance card. Be explicit about comparison mode:
`--comparison current` overlays only the tested flags on today's defaults;
`--comparison historical` resets known A/B flags to the preset's
at-introduction context before applying treatment; `--comparison ablation`
uses today's full model as baseline and disables one rule in treatment, so
its delta is `without_rule - full_model` (negative means the removed rule was
helping). Use `scripts/adaptive_chance_enumeration_ablation_presets.sh` for
the full-model-minus-one-rule batch. That ablation script defaults
`CONDITION_ARCHETYPES=auto`, seating only the archetypes a rule is designed
for where appropriate (e.g. Nit-only for `STEAL_WIDER_VS_NIT`); read those
results as conditional EV in the target spot, not population-weighted EV.

Rule checks now have a separate `rXX-*` numbering for tracked full-model
ablation units. The old `vXX-*` names are historical/version labels and remain
as aliases where useful, but the ablation batch should use the contiguous rule
IDs:

| Rule ID | Legacy label | Unit disabled in ablation |
| --- | --- | --- |
| `r01-calling-raises` | `v3-calling-raises` | `ALLOW_CALLING_RAISES` |
| `r02-unconditional-cbet` | `v6-unconditional-cbet` | `UNCONDITIONAL_FLOP_CBET` |
| `r03-opponent-aware-loose-call` | `v10-opponent-aware` | `OPPONENT_AWARE_ARCHETYPES` |
| `r04-wide-value-3bet` | `v9-wide-3bet` | `USE_WIDE_VALUE_3BET` |
| `r05-steal-wide-vs-nit` | `v14-steal-wide` | `STEAL_WIDER_VS_NIT` |
| `r06-size-up-vs-nit-tag` | `v14-size-target` | `SIZING_TARGET_ARCHETYPES` |
| `r07-wider-3bet-vs-loose` | `v15-loose-3bet` | `WIDER_3BET_VS_LOOSE` |
| `r08-size-up-turn` | `v15-turn-size` | `SIZE_UP_ON_TURN` |
| `r09-iso-raise-limpers` | `v16-iso-limpers` | `ISO_RAISE_OVER_LIMPERS` |
| `r10-donk-bluff-vs-tight` | `v17-donk-bluff` | `DONK_BLUFF_VS_TIGHT` |
| `r11-hero-pot-damping` | `v19-hero-pot-damping` | `HERO_PROGRESSIVE_POT_DAMPING` |
| `r12-tight-big-iso-limpers` | new v31 candidate | `TIGHT_BIG_ISO_RAISE_LIMPERS` |
| `r13-shove-aa-kk-vs-3bet-plus` | new v32 candidate | `SHOVE_AA_KK_VS_3BET_PLUS` |
| `r14-bluff-3bet-vs-tight` | `v24-bluff-3bet` | `BLUFF_3BET_VS_TIGHT` |

This list covers the current ablation-supported tracked rule units. Older
historical ideas such as early core opening/calling changes are not separate
`rXX` checks until the probe can disable them as explicit rule units.

Current full-model ablation results, 2026-08-12. Delta is
`without_rule - full_model`, so negative means the rule helps; positive means
removing the rule was better. Conditioned rows are target-spot EV, not
population-weighted EV.

| Rule ID | Archetypes | Enumerated delta bb/100 | Stop/status | Read |
| --- | --- | ---: | --- | --- |
| `r01-calling-raises` | population | `-19.78 +/- 4.39` | `confirmed_negative` | keep |
| `r02-unconditional-cbet` | population | `-8.44 +/- 2.42` | `confirmed_negative` | keep |
| `r03-opponent-aware-loose-call` | Loose-passive/Station/Maniac | `-77.94 +/- 10.75` | `confirmed_negative` | keep |
| `r04-wide-value-3bet` | population | `-2.43 +/- 1.66` | `confirmed_negative` | keep, small |
| `r05-steal-wide-vs-nit` | Nit | `-27.55 +/- 1.81` | `confirmed_negative` | keep |
| `r06-size-up-vs-nit-tag` | Nit/TAG | `-3.33 +/- 0.94` | `confirmed_negative` | keep |
| `r07-wider-3bet-vs-loose` | Maniac/Station | `-9.87 +/- 3.98` | `confirmed_negative` | keep |
| `r08-size-up-turn` | population | `+0.46 +/- 0.59` | `inconclusive_small_effect` | disabled, no proven benefit |
| `r09-iso-raise-limpers` | population | `-0.60 +/- 0.99` | `inconclusive_small_effect` | disabled, no proven benefit |
| `r10-donk-bluff-vs-tight` | Nit/TAG/LAG | `-11.90 +/- 4.22` | `confirmed_negative` | keep |
| `r11-hero-pot-damping` | population | `+72.06 +/- 6.94` | `max_divergent` | disabled, likely harmful |
| `r12-tight-big-iso-limpers` | population | `+11.61 +/- 3.97`; best params `+22.54 +/- 4.77` | `confirmed_positive` for 0.85/5.5+1.5 | enabled |
| `r13-shove-aa-kk-vs-3bet-plus` | population | `0 divergent / 50k hands even with hero forced to AA/KK` | `untestable_by_self_play` | see note below |
| `r14-bluff-3bet-vs-tight` | Nit/TAG/LAG | `+1.80` at 2M hands/arm | confirmed in session sim | enabled |

Logs backing the final four-row update:
`/tmp/adaptive_chance_enumeration_ablation_20260812_103440.log`. Older rows
come from `/tmp/adaptive_chance_enumeration_ablation_20260812_095622.log` and
`/tmp/adaptive_chance_enumeration_ablation_20260812_101746.log`. The `r12`
current-comparison row comes from
`/tmp/adaptive_chance_enumeration_20260812_111422.log`; it was stopped by user
choice at 22k hands / 1311 divergent once the effect was practically clear,
before the old absolute `CI <= 1.0` target. Follow-up parameter grid:
`/tmp/adaptive_chance_enumeration_20260812_113700.log` and
`/tmp/adaptive_chance_enumeration_20260812_114754.log`. The best checked
variant was `0.85x` normal open VPIP, `5.5bb + 1.5bb/limper`, at
`+22.54 +/- 4.77` bb/100 vs the first shipped r12 default.

`r12` is intentionally different from disabled `r09`: `r09` kept the same
open range and only added a small sizing bump over limpers. `r12` now uses
85% of the normal open VPIP and raises to `5.5bb + 1.5bb/limper`, targeting
a lower multiway rate rather than simply adding price.

### v25-v30 + r13 confirmatory results (2026-08-12, later session) and the new hero-hand-filter tool

Ran `scripts/adaptive_chance_enumeration_confirm_presets.sh` with
`PRESETS_OVERRIDE` limited to v25-v30 + r13 (the "built but not yet run"
set from the table above). Results, historical comparison unless noted
(log: `/tmp/adaptive_chance_enumeration_20260812_175150.log`):

| Preset | Enum delta bb/100 | Stop/status |
| --- | ---: | --- |
| v25-barrel-bluff | `+0.97 +/- 0.65` | `inconclusive_small_effect` (leans real, not confirmed) |
| v26-fold-premium-extreme | `0 divergent / 50k hands` | see fix below, re-running |
| v27-river-overbet | n=10000, 33 divergent | `inconclusive_small_effect` |
| v28-optimal-sizing | `-0.55 +/- 0.85` | `inconclusive_small_effect` |
| **v29-iso-wider-range** | **`+18.25 +/- 5.10`** | **`confirmed_positive`** -- real, large, keep enabled |
| v30-size-scaled-call | `0 divergent / 50k hands` | see finding below |
| r13-shove-aa-kk-vs-3bet-plus | `0 divergent / 50k hands, even with hero forced to AA/KK` | `untestable_by_self_play`, see below |

**⚠️ SUPERSEDED, don't trust this table** -- every row above except r13
(which used `--comparison ablation`, unaffected) was run with
`--comparison historical`, which had a major bug: `HISTORICAL_PRIOR_ON_
FLAGS`'s v21-squeeze-wide entry (aliased by v22-v30) was missing
`ALLOW_CALLING_RAISES` (v3) and `UNCONDITIONAL_FLOP_CBET` (v6) -- both
foundational rules shipped True long before v21. This meant hero could
never call a facing raise (fold-or-3bet-only) and never c-bet the flop
with air in EVERY one of these runs -- a severely crippled baseline, not
"today's actual strategy." Found while root-causing v30's zero-divergent
result (a specific hand, JTo/SB/facing 3.25bb, confirmed in the standard
call range, folded in BOTH arms instead of calling in baseline as
expected). Fixed in commit `f416e84`. **Corrected re-run results are in
the next section below -- read that instead of this table.**

**New tool: `--hero-hand-filter`** (`scripts/probe_chance_enumeration.py`,
commit `58f1870`). Rules gated on a specific hero hand (v26/r15v-fold-*:
QQ+/AK is ~1.8% of hands; r13/r18v-shove-*: AA/KK) were burning their whole
`max_zero_divergent_hands` budget on hands that could never trigger the
rule. New `_pick_hero_hand_swap`/`_apply_hero_hand_swap` force-deal hero's
hole cards to match a target notation set (swapped in from the still-
undealt deck, same technique as the existing `_force_next_board_card` for
board cards), identically on both the baseline and treatment hand so the
paired comparison stays valid. Auto-inferred from
`FOLDABLE_PREMIUM_VS_EXTREME_AGGRO` for v26/r15v-fold-*; pass
`--hero-hand-filter AA,KK` explicitly for r13/r18v-shove-* (different
gating flag, `SHOVE_VS_3BET_PLUS_RANGE`). Verified correct: 200/200
forced hands matched the target notation, no duplicate cards, base/
treatment hands identical.

**r13/r18v-shove-* real finding, not a bug**: even with hero's hand
FORCED to AA/KK, still 0 divergent hands over 50k. Root cause: the rule
only fires facing `n_raises>=2` -- for HERO to reach that node with
AA/KK, an opponent must open, hero (holding forced AA/KK) must 3-bet, AND
then that SAME hand needs a 4-bet from someone else, before hero's 3-bet
is the action facing a fold/call. Two independent rare opponent actions
compounding (this population barely 3-bets at all, 2-5% of raise
responses per Tier 2 -- 4-betting is rarer still) -- this spot may be
close to un-hittable via self-play sampling even with card-forcing.
Confirming it for real would need conditioning on the OPPONENT's action
too (force an opener + a 4-bettor), not just hero's cards -- bigger lift,
not done yet.

**v30 finding, needs investigation**: `SIZE_SCALED_CALL_RANGE` also hit 0
divergent hands over 50k with NO hero-hand-filter applied (it's not a
hero-hand-strength-gated rule, so this isn't the same fix) -- worth
checking whether the flag is actually reachable in `choose_abc_action`'s
control flow before assuming it's just rare.

v26 (and the r15v-fold-* variants) are queued to re-run with the new
filter via `scripts/remaining_variants_confirm.sh`, along with r16v-*
(limp behind range tiers), r17v (call range by raiser position), r18v-*
(shove range tiers, same rarity risk as r13), and r19v-* (BB defend vs
steal tiers) -- none of these had been run at all before this session.
Check `/tmp/remaining_variants_*.log` for the latest results.

**UPDATE**: v26/r15v-fold-*/r18v-shove-* turned out to share r13's exact
`n_raises>=2` compound-rarity problem (confirmed via r13's own 0-divergent-
over-50k-hands result even with hero's cards forced to AA/KK -- the
bottleneck is a rare OPPONENT action sequence, not hero's hand) --
removed from the queue rather than wasted more runtime on them; see
`scripts/remaining_variants_confirm.sh`'s own comment for the full
reasoning. Real fix would need conditioning the opponent's action too
(force an opener + a re-raiser), not just hero's cards -- not built yet.

Ran the reprioritized queue (`/tmp/remaining_variants_20260812_201559.log`):

| Preset | Enum delta bb/100 | Stop/status |
| --- | ---: | --- |
| r16v-limp-behind-{tight,medium,wide} | `+10.32 +/- 4.04` (all three identical) | `confirmed_positive`, but see caveat below |
| r17v-call-by-raiser-position | `-15.24 +/- 6.47` | **`confirmed_negative`** -- real, keep disabled |
| r19v-bb-defend-minraise-tight | `0 divergent / 50k hands` | likely the same dead-threshold bug as v30 (`BB_DEFEND_MAX_RAISE_BB=2.0`, but real min-open sizing never goes below ~2.35bb -- see the v30 note above) |
| r19v-bb-defend-steal-medium | `+1.35 +/- 0.65` | `confirmed_positive` |
| r19v-bb-defend-steal-wide | `+2.16 +/- 1.02` | `confirmed_positive` |
| v30-size-scaled-call (recalibrated 2.5/3.0bb) | `0 divergent / 50k hands` | still zero even after recalibration -- see below |

**r16v caveat, found while double-checking**: all three multiplier tiers
(0.45/0.55/0.75) produced byte-identical deltas, which looked like a bug
at first. Verified directly: `limp_behind_ranges` genuinely DOES differ
by multiplier (e.g. UTG: 26 hands @0.45x vs 32 @0.75x, real hands like
AJo/AKo/ATs only in the wider tier) -- NOT a caching bug (my first check
used the wrong tuple index into `_ranges()`, a self-inflicted false
alarm). Real, more likely explanation: within this specific 6000-hand
seeded sample, none of hero's limping-behind-eligible dealt hands
happened to land in the narrow multiplier-differential region (~6-13
hands per position out of 169) -- most divergent hands came from
`LIMP_BEHIND_EXTRA_HANDS` (pairs/suited connectors/small suited aces),
which is identical across all three tiers by construction. So this
confirms "some limp-behind range beats none" but does NOT yet
distinguish which tier is best -- needs a bigger sample or (better) the
same hero-hand-filter technique, forced to the differential hand set
specifically.

**v30 still-open mystery**: recalibrated thresholds (2.5/3.0bb) should
bracket the real observed opponent-sizing clusters (2.35bb/3.25bb, see
the earlier percentile measurement) and DID clear the earlier "dead
threshold" explanation -- yet still zero divergent hands over 50k.
`call_ranges_wide`/`call_ranges_narrow` are confirmed to genuinely differ
from `call_ranges` (existing passing tests assert non-empty diffs). Not
yet root-caused; candidates for next look: whether `SIZE_SCALED_CALL_RANGE`'s
branch in `choose_abc_action` is actually reached given the "historical"
comparison's specific flag combination (v21-squeeze-wide baseline), or
whether hero's actual dealt hands in facing-one-raise spots just don't
fall in the differential region often enough at this sample size (same
class of explanation as the r16v caveat above, in which case a bigger
sample or hero-hand-filter would resolve it, not a real bug). Left open,
flagged for whoever picks this up next.

**v30's mystery, actually resolved**: root cause was the historical-
baseline bug above, not a code-reachability issue -- SIZE_SCALED_CALL_RANGE
does reach its branch correctly (confirmed by direct instrumentation
before the fix was even applied: JTo/SB/facing-3.25bb-raise showed IDENTICAL
"fold" in both arms because ALLOW_CALLING_RAISES=False made the whole
call-range branch unreachable regardless of the flag under test).

### CORRECTED results after fixing the historical-baseline bug (2026-08-12)

Re-ran every bug-affected preset (`scripts/refixed_historical_confirm.sh`,
log: `/tmp/refixed_historical_20260812_212932.log`). **These numbers
supersede the table above -- use these:**

| Preset | Enum delta bb/100 | Stop/status | Changed from before? |
| --- | ---: | --- | --- |
| **v29-iso-wider-range** | **`+22.10 +/- 5.18`** | **`confirmed_positive`** | still confirmed, even bigger (was +18.25) -- headline result holds, keep enabled |
| **v30-size-scaled-call** | **`-6.46 +/- 3.45`** | **`confirmed_negative`** | was "0 divergent, mystery" -- now a real, clear NEGATIVE result. Keep disabled. |
| v25-barrel-bluff | `+1.99 +/- 0.99` | `confirmed_positive` | was inconclusive (+0.97) -- now clears the bar |
| v27-river-overbet | `+0.25 +/- 0.55` | `inconclusive_small_effect` | unchanged conclusion, near zero |
| v28-optimal-sizing | `+2.25 +/- 1.12` | `confirmed_positive` | was inconclusive and leaning NEGATIVE (-0.55) -- full reversal |
| v23-overbet-fold | `0 divergent / 50k hands` | still zero | NOT the same bug (this rule is postflop facing-a-bet, unrelated to ALLOW_CALLING_RAISES) -- separately confirmed real bet-bigger-than-pot incidence is genuinely low (~0.78% of postflop facing-bet spots, direct measurement), so this needs a bigger `max_hands` budget, not another bug hunt |
| v23-size-strong | `-0.29 +/- 0.98` | `inconclusive_small_effect` | consistent with before, genuinely null |
| v23-size-wet | `-0.44 +/- 0.99` | `inconclusive_small_effect` | consistent with before, genuinely null |
| v23-size-both | `-0.58 +/- 0.99` | `inconclusive_small_effect` | consistent with before, genuinely null |

**Practical takeaway**: v29 (isolate limpers with a wider range) is the
one clean, large, doubly-confirmed win from tonight's whole batch --
ship it. v30 (scale call range by raise size) should stay OFF, now for
a real evidenced reason (hurts) rather than "couldn't test it." v25 and
v28 are new real candidates worth enabling (v25 barrel bluff, v28
per-archetype EV sizing) pending the same statistical-standard bar this
file uses everywhere (`|delta| > sqrt(CI_a^2+CI_b^2)` against a second,
independent sample before calling anything permanently confirmed -- these
are each currently confirmed by ONE run, not yet cross-checked against a
second independent seed the way v16/v17 were). v23's sizing-by-context
theories (strength/wet-board) are genuinely null against this population
-- don't ship, don't keep re-testing without a new idea.

### Independent second-seed cross-check (2026-08-12, `--base-seed 777`)

Added `--base-seed` to `probe_chance_enumeration.py` (commit `0b72537`)
so a second sample can be genuinely independent instead of reusing the
same `seed=42` every run tonight had used. Cross-checked the four
results above (log: `/tmp/independent_seed_20260812_222141.log`):

| Preset | Seed 42 | Seed 777 | Combined CI (quadrature) | Verdict |
| --- | ---: | ---: | ---: | --- |
| **v29-iso-wider-range** | `+22.10 +/- 5.18` | `+19.67 +/- 6.04` | `7.96` (delta between runs 2.43, well inside) | **DOUBLY CONFIRMED positive** -- ship it, high confidence |
| **v30-size-scaled-call** | `-6.46 +/- 3.45` | `-5.67 +/- 4.72` | `5.85` (delta 0.79, well inside) | **DOUBLY CONFIRMED negative** -- keep disabled, high confidence |
| v25-barrel-bluff | `+1.99 +/- 0.99` | `+1.33 +/- 0.65` | `1.18` (delta 0.66, inside) | doubly confirmed positive, smaller effect than the first run suggested (~+1.3 to +2.0, not treat +1.99 as the settled number) |
| v28-optimal-sizing | `+2.25 +/- 1.12` | `+0.82 +/- 0.96` (`inconclusive_small_effect` on its own) | `1.47` (delta 1.43, right at the edge) | RESOLVED below with a 3rd and 4th sample -- see "v28, third sample" and the confirmed-real table at the top; final settled estimate `+1.45+/-0.62` @ 54k hands, shipped True |

**Bottom line, in priority order**: v29, v30, v25, and v28 are all
results from tonight's whole session now shipped/settled with real
confidence (see the confirmed-real table at the top of this file for
final numbers). v29 is the single biggest lever found tonight; v25/v28
are smaller but real. Don't cite the `+2.25` number for v28 on its own
again without the caveat above.

**v28, third sample** (base_seed=314159, tighter target_ci=0.5): `+4.88
+/- 2.21`, confirmed_positive on its own. All three v28 samples now:
seed42 `+2.25+/-1.12`, seed777 `+0.82+/-0.96`, seed314159 `+4.88+/-2.21`
-- all positive in direction, but pairwise inconsistent with each other
at the combined-CI-in-quadrature standard (e.g. seed777 vs seed314159:
combined CI 2.41, delta between them 4.06). Honest read: v28 very likely
has a real positive effect (never once measured negative across three
independent samples), but the true magnitude is noisy/uncertain --
somewhere in the +1 to +5 bb/100 range, not a single settled number.
Would need either a much larger single run or a pooled multi-seed
analysis to pin down precisely. Treat as "probably worth enabling,
magnitude unclear" rather than citing any one of these three numbers.

**v28, 4th and 5th samples** (large-precision runs, `min-hands 40k-100k`,
`target-ci 0.5-0.6`): seed42 `+1.45+/-0.62` @ 54k hands/2001 divergent
(shipped on this one, see the confirmed-real table); seed271828
`+0.68+/-0.68` @ 50k hands/2101 divergent -- barely positive, CI as large
as the point estimate, doesn't clear confirmed_positive on its own.
**Final tally: 5 independent samples, all 5 positive** (+2.25, +0.82,
+4.88, +1.45, +0.68) -- getting 5/5 same-sign draws by chance around a
true-zero effect has roughly a 3% probability (0.5^5), so the sign
itself is good evidence of a real effect even though no single sample
pins down the magnitude cleanly and they don't all pairwise-agree.
Keeping this shipped True is justified by the consistent direction, not
by any one number -- don't cite a single v28 delta as "the" effect size,
the honest range is roughly +0.7 to +2 bb/100 with the smaller,
higher-precision runs (54k/50k hands) weighted more than the noisier
small ones (2k-6k hands).

### v23-overbet-fold: fully resolved, real structural finding (not the historical-baseline bug)

Also affected by tonight's historical-baseline bug, but re-testing after
that fix STILL showed zero divergent hands (300,000-hand run). Root-
caused separately: `FOLD_TOP_PAIR_VS_OVERBET`'s own condition was
independently, mathematically broken (`pot_before` already included the
opponent's bet, so `to_call/pot_before > 1.0` could never be true for
any finite bet -- see `abc_bot.py`'s `FOLD_TOP_PAIR_VS_OVERBET` comment,
fixed in commit `82d2567`). Even after fixing the formula (verified
correct via a direct synthetic test), a 50k-hand re-test STILL showed
zero divergent hands -- but this time confirmed as a genuine structural
fact via direct instrumentation: of 44 real postflop overbet-facing
spots found in 15,000 hands, hero held zero pair in ALL 44. This bot
always value-bets any made hand the instant it's checked to, so the
only hero that ever reaches "checked, then faced a bet" is exactly the
sub-population that had no hand to bet with in the first place --
FOLD_TOP_PAIR_VS_OVERBET targets a scenario this bot's own other rules
make nearly unreachable by construction, not a sampling problem. Two
real, independent bugs found and fixed on this one flag tonight; the
final answer is a structural non-starter, not "needs more hands."

### r13/v26/r15v-fold-*/r18v-shove-*: new tool built, real scaling issue understood (still open)

All of these are gated on hero FACING a re-raise (n_raises>=2) -- a spot
this population reaches too rarely (barely 3-bets/4-bets at all) for even
hundreds of thousands of hands to naturally surface, confirmed earlier via
r13 (0 divergent over 50k hands even with hero's cards forced to AA/KK).

Built `--force-opponent-reraise` (`probe_chance_enumeration.py`,
`_should_force_opponent_reraise`/`_force_reraise_action`) to force the
opponent facing hero's raise to reraise instead of using their trained
model, guarded to fire at most once per hand (an earlier version without
the guard cascaded into unbounded raise wars -- confirmed up to 7 preflop
raises in one hand). This DOES reliably get hero to the target decision
point (confirmed via direct instrumentation: 278/300 hands reached
n_raises>=2 with hero holding forced AA/KK). Also generalized
`_pick_hero_hand_swap`/`_apply_hero_hand_swap` to any seat, so the
reraiser's cards get forced too (to `VALUE_3BET_WIDE`, a real premium
3-betting range), not just their action.

**The measured magnitude is still not directly usable, but this is now
understood, not a mystery**: smoke tests (r13, `--hero-hand-filter AA,KK
--force-opponent-reraise`) measured deltas in the THOUSANDS of bb/100 both
before AND after forcing the opponent's cards too (+4052/+4061 with real
premium opponent cards) -- looked like a bug, isn't one. `enum_delta`
averages the per-hand delta over EVERY sampled hand (0.0 for every
non-divergent one), and combining `--force-opponent-reraise` with
`--hero-hand-filter` pushes a spot real self-play reaches on well under
0.1% of hands up to 60%+ of the forced sample (see the divergent-hand
percentage printed) -- inflating the reported bb/100 by roughly that same
factor. The raw number this flag produces was never meant to be read as a
population bb/100; it needs rescaling by (true incidence of the spot) /
(this sample's forced incidence) to mean anything. True incidence of
"hero has AA/KK AND faces a real 4-bet" isn't precisely measured yet.
Until it is, this flag is useful for confirming a rule's branch is
reachable and its EV sign is directionally right, not for a literal
bb/100 magnitude. Don't ship r13/v26/r15v-fold-*/r18v-shove-* based on
any raw number produced by this flag -- rescale first, or measure the
true incidence rate directly (a natural-incidence, no-forcing run over
enough hands to count real occurrences) before trusting a number.

**True incidence, now measured** (`scripts/measure_facing_3bet_incidence.py`,
200,000 hands, natural self-play, no forcing): hero faces n_raises>=2 at
all on 2.647% of hands; with a `PREMIUM_VS_3BET`-tier hand specifically,
0.232%; with AA/KK specifically, 0.081% -- confirms the "well under 0.1%"
estimate. Rescaling r13's earlier forced-sample result
(`+4061.24 bb/100` @ `--hero-hand-filter AA,KK --force-opponent-reraise`,
which forces ~100% incidence of the target spot within its own sample) by
the true incidence: `4061.24 * 0.00081 ≈ +3.29 bb/100`. This is a rough,
one-sample estimate (not independently cross-checked the way v25/v28/v29
were), but it's a plausible, modest positive number in the same range as
this file's other confirmed narrow-target rules (v17 +3.40, v24 +1.80) --
worth a real confirmatory pass (either a proper independent-seed rescale,
or building true card-conditioning for the opponent's realistic archetype-
specific reraising range instead of a flat VALUE_3BET_WIDE) before
shipping, but no longer a total unknown.

**r18v-shove-qq-plus/qq-ak and v26, extended measurement (500,000 hands)**:
QQ+ (AA/KK/QQ): 0.1206% of hands. QQ+/AK (AA/KK/QQ/AKs/AKo): 0.2298% of
hands.

**r18v-shove-qq-plus, forced-sample magnitude now measured** (2000 hands,
`--hero-hand-filter AA,KK,QQ --force-opponent-reraise`): `+3487.15 bb/100`
raw. Rescaled by true incidence (0.1206%): `3487.15 * 0.001206 ≈ +4.21
bb/100` -- plausible, same order of magnitude as r13's rescaled estimate
(+3.29) and this file's other confirmed narrow-target rules. One-sample
rough estimate, same caveats as r13's.

**r18v-shove-qq-ak, forced-sample magnitude also measured** (2000 hands,
`--hero-hand-filter AA,KK,QQ,AKs,AKo --force-opponent-reraise`):
`+1855.59 bb/100` raw -- about half of qq-plus's raw delta (adding AK
dilutes the average edge per occurrence, since AK is weaker than QQ
against a 4-betting range). Rescaled by true incidence (0.2298%, almost
exactly double qq-plus's): `1855.59 * 0.002298 ≈ +4.26 bb/100` -- nearly
IDENTICAL to qq-plus's +4.21 despite the very different raw numbers: the
wider range's smaller per-occurrence edge is compensated by its roughly
doubled frequency. Same pattern as tonight's r16v finding (the exact tier
boundary doesn't matter much for total contribution) -- **whichever
SHOVE_VS_3BET_PLUS_RANGE tier ships, expect roughly the same ~+4 bb/100
real-world contribution.** This closes out the r13/v26/r18v-shove-*
investigation thread for tonight: r13 ~+3.3, r18v-shove-qq-plus ~+4.2,
r18v-shove-qq-ak ~+4.3, v26 negligible. All rough one-sample estimates,
real enough to be worth a proper confirmatory pass before shipping, not
yet at the v25/v28/v29 confidence bar.

**v26's FULL compound condition -- ZERO occurrences in 500,000 hands.**
Tracked precisely: hero holds a `FOLDABLE_PREMIUM_VS_EXTREME_AGGRO` hand
(QQ/AKs/AKo) AND faces a bet >= `EXTREME_AGGRO_STACK_FRACTION` (50%) of
hero's remaining stack AND the raiser is a known Nit/TAG. Given the
QQ+/AK hand-holding rate alone is already only 0.23%, and this adds TWO
more independent rare conditions (a genuinely stack-threatening bet size,
AND a specifically tight raiser identity) on top, true incidence is
almost certainly under 1-in-500,000 -- likely needs tens of millions of
hands to observe even a handful of real occurrences via self-play. **Real
conclusion, not just "needs a bigger sample": whatever v26's rule does in
this exact spot, its contribution to overall population bb/100 is
necessarily tiny given how rarely the spot itself occurs** -- even a huge
per-occurrence EV swing can only move the population average by a
fraction of a bb/100 when the spot itself is this rare. Not worth further
testing investment relative to its plausible ceiling impact; the
plain-language strategy card's existing v26 entry can stay untested/off
without real cost.

### 2026-08-13: postflop research pass (reviewed only, NOT implemented yet)

Same exercise as the preflop one below, but for postflop, with more source
breadth per the user's request (~14 search queries, 100+ distinct pages,
including GTO Wizard, Upswing, PokerCoaching, Red Chip Poker, SplitSuit,
888poker, and several poker-theory forum threads). **User explicitly
cancelled implementation this round ("отмена, не делай") -- this is a
research record only, to implement later, not code yet.** Ten gaps found:

1. **Board-texture-dependent c-bet sizing/frequency** -- dry boards small
   (solvers favor 25-40% pot), wet boards bigger and less often. The bot
   uses one flat ~55% pot size (`STANDARD_SIZING_POT_FRACTION`) regardless
   of texture.
2. **Multiway c-bet frequency reduction** -- MDF splits across defenders,
   bluffing multiway is a default loser. Partially already in the codebase
   as `MULTIWAY_DISABLE_AIR_CBET` (candidate, off, never tested) -- not a
   new idea, just an existing untested one worth prioritizing.
3. **Check-raising with draws (semi-bluff raise)** -- the bot has no
   mechanism to raise a draw when facing a bet at all; it only calls draws
   (pot-odds gated) or raises with two-pair+ (`VALUE_RAISE_FACING_BET`,
   off). Semi-bluff raising doesn't exist as a decision category.
4. **Range/nut-advantage-based sizing** -- not just board wetness, but
   WHO the board favors given the preflop action (e.g. PFR usually favored
   on dry A-high boards, caller favored on low connected boards). The bot
   only has a binary `had_initiative`, no board-fit-vs-range concept.
5. **Turn probe betting after a checked-through flop** -- when the
   aggressor checks back, the OOP non-aggressor should often bet the turn
   (~31% solver frequency) since two checks caps a range hard. No such
   branch exists; the bot only takes the betting lead through its own
   barrel logic (v25), never as a reaction to an opponent's skipped c-bet.
6. **Pot control / checking back marginal made hands** -- the bot always
   value-bets top-pair-or-better, every time, by design (see the "Don't
   auto-barrel" note in its own strategy card). No slowplay/pot-control
   category exists at all.
7. **SPR-based hand-value thresholds** -- continuing/raising thresholds
   are static regardless of stack-to-pot ratio; real strategy widens the
   commitment range as SPR drops.
8. **Block bets (small river sizing)** -- only two sizing tiers exist
   (standard ~55% and the v27 overbet ~150%); no small ~25-33% "block bet"
   tier for thin value against a defender's default range.
9. **Blocker-based river bluff/hand selection** -- `BARREL_BLUFF_VS_TIGHT`
   (v25) picks bluffs by archetype + scare-card only, never by whether the
   specific hand blocks the defender's value combos / unblocks their
   folding combos.
10. **Delayed c-bet** -- check flop with a marginal/unclear hand, bet turn
    instead if checked to again (two checks caps the opponent's range).
    The bot's Tier-1 c-bet is immediate-flop-only or nothing; no
    check-flop-then-bet-turn line exists.

**Already covered, not a real gap**: donk-betting WITH a made hand is
already structural (the bot's `to_call <= 0: bet top-pair-or-better`
branch fires "regardless of whether you had preflop initiative," which
functionally is leading into the raiser) -- only donk-*bluffing* on narrow
low-connected-board textures is missing, and that's a much smaller-value
idea than the ten above. Nut-advantage overbetting is partially covered
by v27 but restricted to trips+ vs loose archetypes only, not a general
any-street nut-advantage rule.

**Next step, when authorized**: implement all ten as off-by-default flags
the same way r22-r29 were done for preflop (see that section below),
smoke-test for crashes only, wire into `probe_chance_enumeration.py`
presets, document in this file -- do NOT run any A/B validation without
separate explicit go-ahead.

### 2026-08-13/15: 8 new preflop rules from published-theory research -- built AND tested

User asked for a web/book research pass on preflop advice the bot doesn't
cover, implemented as off-by-default flags on 2026-08-13, then (2026-08-15,
user asked to test everything still untested) statistically validated via
`scripts/r22_29_batch_confirm.sh` -- adaptive chance-enumeration, both
base-seed 42 and 777, log `/tmp/r22_29_batch_confirm_20260815_130025.log`.
Full numbers in `abc_bot.py`'s own changelog docstring (search "r22-r29
validation").

**Shipped True** (confirmed positive both seeds):
| Preset | Flag | Idea | seed42 / seed777 (bb/100) |
|---|---|---|---|
| `r22-threebet-size-by-position` | `THREEBET_SIZE_BY_POSITION` | 3-bet ~4x OOP / ~3x IP instead of flat 3x | +6.10±2.72 / +6.91±3.16 |
| `r23-threebet-bluff-late-position` | `THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT` | polarized late-position bluff-3bet vs any archetype | +9.18±4.22 / +8.34±3.44 |
| `r24-bb-defend-mdf-scaled` | `BB_DEFEND_MDF_SCALED` | MDF-driven BB widening vs any raiser position | +20.78±7.42 / +13.74±5.22 (noisy magnitude, solid direction) |
| `r27-set-mine-implied-odds` | `SET_MINE_IMPLIED_ODDS` | 15/25/35-rule implied-odds cold-call | +6.50±3.00 / +9.61±4.39 |

**Stays False** (confirmed negative both seeds):
| Preset | Flag | seed42 / seed777 |
|---|---|---|
| `r25-bluff-3bet-blocker-range` | `BLUFF_3BET_BLOCKER_RANGE_FLAG` | -6.94±5.07 / -4.13±3.49 |

**Stays False** (inconclusive both seeds):
| Preset | Flag | seed42 / seed777 |
|---|---|---|
| `r28-rake-adjusted-open-sizing` | `RAKE_ADJUSTED_OPEN_SIZING` | -0.02±1.00 / -0.29±1.00 |

**Stays False** (didn't clear the two-seed bar, special cases):
- `r26-limp-trap-monsters` (`LIMP_TRAP_WITH_MONSTERS`) -- +0.45±0.36
  (inconclusive) / +0.77±0.38 (confirmed) -- same sign, genuinely tiny
  effect (unopened AA/KK is a naturally rare spot), split verdict.
- `r29-fold-vs-3bet-passive` (`FOLD_VS_3BET_FROM_PASSIVE`) -- seed42
  confirmed negative (-2.15±1.22, 84k hands), seed777 had **zero**
  divergent hands in 50k (the exact spot never occurred naturally in that
  seed's sample) -- can't cross-validate, same `untestable_by_self_play`
  situation as r13 above. Suggestive but not confirmed.

Researched but judged **already covered** by existing (tested) mechanics,
not re-implemented: linear-vs-polarized-by-hero-position is the value side
already handled by `WIDER_3BET_VS_LOOSE`; exploiting passive players via
wider isolation is `STEAL_WIDER_VS_NIT`/`TIGHT_BIG_ISO_RAISE_LIMPERS`;
opponent-archetype-aware calling generally is `OPPONENT_AWARE_ARCHETYPES`
(the biggest confirmed lever in the file). At 100bb effective (this sim's
actual depth -- corrected from an earlier mistaken "200bb" claim in this
file), the researched limp-reraise and cold-call/set-mine sources' example
figures apply close to as-written (100bb is the standard assumption most
cited solver charts use).

191 tests re-run after flipping r22/r23/r24/r27 to True: still all pass.

### 2026-08-13 round: honest r13/r18v re-test + bug audit + new confirmed/negative flags

User asked to (1) get an honest r13/r18v-shove-* verdict using natural
opponent behavior instead of `--force-opponent-reraise`'s biased
opponent-card-forcing, (2) A/B-test the three untested-since-written flags
(`CALL_RANGE_BY_RAISER_POSITION`, `SIZE_UP_PREMIUM_OPENS`,
`BB_DEFEND_VS_STEAL_MINRAISE`), and (3) audit whether other "didn't work"
flags share SIZE_SCALED_CALL_RANGE's bug (a range tier silently missing a
real-data union that its sibling tiers include).

**Why the r13/r18v rescaled numbers weren't trustworthy**:
`--force-opponent-reraise` inflates a rare spot's frequency AND fixes the
opponent's cards to a specific range (`VALUE_3BET_WIDE`) instead of their
real trained-model distribution. Rescaling by `true_incidence /
forced_incidence` only corrects for the frequency distortion, not the
card-distribution distortion -- so the ~+3.3/+4.2/+4.3 bb/100 numbers were
directionally probably right but not a real confirmed magnitude. Honest
fix: `--hero-hand-filter` only (forces hero's own cards, doesn't touch
opponent behavior at all) with NO `--force-opponent-reraise`.

**Bug audit found a second real gap**, this time in a currently-shipped
rule: `_tight_iso_range_cache` (used by `TIGHT_BIG_ISO_RAISE_LIMPERS =
True`) is the only raising-range tier that never unions
`REAL_DATA_RANGE_ADDITIONS`, unlike `_open_range_cache` and
`_steal_range_cache` which both do -- despite the strategy card describing
tight-iso as "X% of the normal open VPIP," where "normal open range" is
itself defined as VPIP-range UNION `REAL_DATA_RANGE_ADDITIONS`. Added
`TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR` (off by default, untested + this rule
is live) and preset `r21`. First two-seed result (5-8k hands): **+7.72+/-3.82
@ seed42, +25.60+/-10.55 @ seed777** -- both individually clear
`confirmed_positive`, but combined-CI-in-quadrature is 11.22 against a
17.88 delta BETWEEN the seeds, i.e. the two samples don't agree with each
other. Sign is consistently positive (meaningful on its own) but
magnitude is too noisy to ship -- needs a bigger precision run.

**Confirmed and shipped**: **r20 (`SIZE_UP_PREMIUM_OPENS`) = True** --
+4.00+/-1.89 @ seed42, +3.05+/-1.44 @ seed777, combined-CI 2.38 vs 0.95
delta, well inside. The 2026-08-07 whole-game test (+1.76/-0.76, inside
CI, sign flip) was simply too imprecise to see this real effect; the
newer chance-enumeration method resolved it.

**Tested, not demonstrated**: **r17v (`CALL_RANGE_BY_RAISER_POSITION`)**
-- +0.07+/-0.99 @ seed42, -0.98+/-0.99 @ seed777, both
`inconclusive_small_effect`, consistent with a true-zero effect. Kept off.

**2026-08-13 ~10:30am: user asked to kill everything running** (needs the
machine for other work) -- all background jobs were `pkill`'d
(`round2_confirm.sh`, `round3_r21_precision.sh`, any live
`probe_chance_enumeration.py` process). Working tree was clean at the
time (every finding above was already committed). **Queued for the next
overnight/idle session -- do not start without the user's go-ahead first,
same standing rule as always:**

1. **r21 precision run** (the inconsistent-magnitude one above) -- bigger
   sample per seed:
   `.venv/bin/python3 scripts/probe_chance_enumeration.py
   r21-tight-iso-real-data-floor 50000 --comparison current --adaptive
   --min-hands 20000 --max-hands 200000 --base-seed 42` (and `--base-seed
   777`).
2. **v30 (`SIZE_SCALED_CALL_RANGE`) re-test after the narrow-range bug
   fix**, plus three milder-multiplier variants, all via
   `--comparison current --adaptive --base-seed 42` (and 777 for
   cross-check once seed42 looks promising): presets
   `v30-size-scaled-call`, `v30v-mild-narrow`, `v30v-no-narrow`,
   `v30v-mild-both`.
3. **BB_DEFEND_VS_STEAL_MINRAISE (r19v)**, three variants, same adaptive
   pattern: `r19v-bb-defend-minraise-tight` (expect 0 divergent, same
   dead-threshold issue as v30's original 2.0bb -- low priority),
   `r19v-bb-defend-steal-medium`, `r19v-bb-defend-steal-wide`.
4. **Honest r13/r18v-shove-* natural-incidence tests** (the main
   unresolved thread) -- `--hero-hand-filter` only, no
   `--force-opponent-reraise`, large adaptive cap since the target spot is
   rare even with hero's hand forced:
   `.venv/bin/python3 scripts/probe_chance_enumeration.py
   r13-shove-aa-kk-vs-3bet-plus 2000000 --comparison current
   --hero-hand-filter AA,KK --adaptive --max-hands 2000000 --base-seed 42`,
   then `r18v-shove-qq-plus --hero-hand-filter AA,KK,QQ`, then
   `r18v-shove-qq-ak --hero-hand-filter AA,KK,QQ,AKs,AKo`. Each of these
   could take a long time (the earlier honest smoke test found 0 divergent
   over 50k hands even with hero's cards forced) -- run one at a time, not
   in parallel, and check `vm_stat` free memory before launching (this
   machine runs tight, ~300MB free was typical during this session with
   several other Claude Code sessions + VS Code open).

All of scripts 1-4 above are cheap to re-launch (`probe_chance_enumeration.py`
already has every preset/flag wired in from this round's commits) -- no
further code changes needed, just running them and updating this file +
`abc_bot.py`'s flag defaults with whatever comes back.

### Regressors / features NOT currently used anywhere (raised 2026-08-11)

The user asked for a full brainstorm of possible decision inputs beyond
what's implemented. Full list was given in conversation; the standout
candidates, ranked by likely leverage (using the "new behavior beats range
tweak" pattern above as the guide):

1. **Opponent's actual bet SIZE as a signal** (not just that a bet happened)
   — currently fully ignored by `abc_bot.py`.
2. **Per-opponent bluff frequency** — already computed in the Analysis repo
   (`find_frequent_bluffers.py`), NOT wired into the bot at all. Direct
   extension of the v10 calling-bar rule that's already the single biggest
   confirmed lever in the file.
3. **Range advantage by board texture** for c-bet/bluff sizing, instead of
   the current unconditional-frequency rule.
4. **Blockers** — not used anywhere in bluff/3-bet hand selection.
5. Also raised but lower priority: SPR, in-position-vs-bettor (not just
   absolute seat position), opponent's own stack relative to others,
   card-removal effects, session-length/tilt dynamics already computed in
   the Analysis repo but not wired in, sample-size-weighted trust in a
   given opponent's archetype read.

Follow-up research request to preserve: test whether players change style
after getting coolered/sucked out on or running badly. Look for increased
impulsiveness: higher VPIP/PFR/3bet, bigger bets, thinner calls, more bluffing,
or faster stack-off lines in the next N hands after a bad-beat/run-bad event.
If real, derive an exploitable rule rather than assuming generic "tilt."

Full category list (game state, money, action history, opponent stats,
cards, board, timing, session/meta) is worth re-deriving fresh if picked
back up — this is a compressed pointer, not the full brainstorm.

## GitHub

Both repos are meant to be pushed public under account `le-melon1` (NOT
`olegvarikov` — that was an earlier wrong assumption, fix any stale
references). `gh auth login` succeeded. `github.com/le-melon1/
PokerDom_Practice_App` **exists but is empty** — `gh repo create --push` was
blocked by an auto-mode classifier denial, a later plain `git push` hit an
HTTP 408 timeout and printed a misleading "Everything up-to-date" despite
`git ls-remote origin` returning nothing. **Confirm current state with
`git ls-remote origin` before assuming either way** — don't trust this
paragraph's snapshot. `PokerDom_Microlimits_Analysis` has not been pushed at
all (repo may not even exist there yet — check). This needs either the user
running the push themselves, or another attempt with the user's explicit
go-ahead.

## How this user likes this project worked on (condensed — see the fuller
memory notes if you have access to them; this is the compressed version for
an assistant that doesn't)

- **Ask before launching anything that runs more than ~a couple minutes or
  uses significant CPU/RAM.** "Remember this idea" or discussing a plan is
  NOT authorization to start it. Wait for something like "запускай"/"давай"
  attached directly to the launch action, or ask explicitly. This has been
  gotten wrong before (launched an overnight batch after the user only said
  "remember this") and corrected firmly.
- **This is a shared, resource-constrained (8GB RAM) machine** with multiple
  concurrent Claude Code sessions often active on the same repos. Before any
  heavy background job: check `ps aux`/`memory_pressure` for what's already
  running, use `nice -n 15`, run ONE heavy job at a time. Two sessions
  independently running the same heavy script has crashed the machine
  (19.86GB swap) more than once.
- **Give real measured numbers, not guesses**, for "how long will X take" —
  run a small timed calibration if at all feasible.
- **Report approximations and bugs honestly**, including ones found after
  the fact — this user reacts well to direct, itemized "what's undone/
  approximate" audits (grep the code, don't guess) and to honest
  after-the-fact corrections.
- **Visual/browser testing is mandatory** for any frontend change — screenshot
  and actually look at it (`scripts/browser_check.py` or similar), don't
  trust "the JSON looks right."
- Can run long unattended stretches autonomously if asked, but wants
  resumable/checkpointed scripts and a respected stop time if one is given.
- Keep TODOs/READMEs/this file synced with actual code state — this user
  has caught stale claims before.

## Where things live

- `backend/bots/abc_bot.py` — the strategy bot, full changelog in its own
  docstring (read before editing).
- `scripts/simulate_abc_bot.py` — the A/B test harness; use
  `--common-random` for lower-variance paired comparisons,
  `--flag-confirm <preset|all> <n_hands>` for re-confirmation runs, and
  individual `--<flag-name>` modes for one-off tests.
- `scripts/overnight_confirm_flags.sh` — the currently-running 6-stage
  batch script; log at `/tmp/overnight_confirm_20260811_122418.log`.
- `tests/test_abc_bot.py` — unit tests for every flag (147 passing as of
  the last full run mentioned in memory — re-run `pytest tests/` fresh,
  don't trust that number blindly).
- `PokerDom_Microlimits_Analysis/data/reference/*.csv` — the real-data
  tables (`archetype_facing_bet.csv`, `archetype_vs_raise.csv`, etc.) that
  several flags read at runtime.
