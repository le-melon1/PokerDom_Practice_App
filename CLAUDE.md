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
-9.66 bb/100).

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
| v28-optimal-sizing | `+2.25 +/- 1.12` | `+0.82 +/- 0.96` (`inconclusive_small_effect` on its own) | `1.47` (delta 1.43, right at the edge) | **NOT doubly confirmed** -- second run alone doesn't clear its own bar; likely a real small positive or noise around a small one, needs a bigger sample before treating as settled the way v29/v30 now are |

**Bottom line, in priority order**: v29 and v30 are the two results from
tonight's whole session worth acting on with real confidence. v25 is
probably real but smaller than it first looked. v28 needs more data
before it's trustworthy -- don't cite the `+2.25` number on its own
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
