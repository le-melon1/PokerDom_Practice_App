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
the actual raise size faced). **These need a follow-up confirmatory batch —
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
flushes progress after every chunk, and stops each preset once `CI <= 1.0`
and `CI <= abs(delta) / 2`, or when the configured hand/divergence caps are
hit. For negative deltas it can stop earlier once `CI <= abs(delta)`, because
that is already enough to classify the flag as worse. Rules that never find
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

Logs backing the final four-row update:
`/tmp/adaptive_chance_enumeration_ablation_20260812_103440.log`. Older rows
come from `/tmp/adaptive_chance_enumeration_ablation_20260812_095622.log` and
`/tmp/adaptive_chance_enumeration_ablation_20260812_101746.log`.

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
