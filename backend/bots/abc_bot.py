"""ABC v11: a simple but COMPLETE decision tree, built on top of the published
Tier-1 ABC guide (PokerDom_Microlimits_Analysis, "ABC-стратегия NL25 — три
уровня"). Tier 1 as written only covers opening ranges + one flop cbet rule;
everything else here was added and then EMPIRICALLY TESTED via
scripts/simulate_abc_bot.py against a population-weighted mix of the
practice app's real behavior-clone bots (80k hands per measurement, 95% CI
reported, monster pots from a known bot-sizing bug excluded -- see that
script's docstring). Revision history, each one a real measured finding:

  v1 (naive): calling a raise with the WHOLE opening range, then playing a
  strict "top-pair-or-better or fold" postflop plan: -7 to -11 bb/100.
  v2: narrower calling range instead of "call what you'd open" -- barely
  moved it (still -7 to -11 bb/100).
  v3: a per-line diagnostic (bucket net bb by preflop role) pinned the leak on
  calling a raise specifically: -74 bb/100 on that bucket alone. Classic
  "fit or fold" -- without initiative and a fold-unless-top-pair plan, hero
  folds most postflop bets regardless of hand, so betting into hero is a free
  roll. Fix: never flat, raise-or-fold only. Re-measured: still -9.5 to -13
  bb/100 -- NOT the whole story.
  v4: fixed a bug in the diagnostic itself (it counted hero as "saw a flop"
  whenever the table did, even if hero had folded). With that fixed, the real
  leak was hands with a free flop (checked around, no raise) where hero
  stayed in: -51.79 bb/100, because betting was gated on "did I raise
  preflop" -- a big hand reached via a free look never got bet for value.
  Fix: value-bet any street regardless of initiative.
  v5: extended "top pair or better" to recognize made straights/flushes (an
  earlier version only checked paired ranks), and added a pot-odds-gated draw
  continuation (flush/open-ended straight draws, call if price <= rough
  draw equity, flop/turn only, never the river). Result: -1.11 bb/100
  (no rake) -- first time within noise of breakeven.
  v6: two more A/B tests against v5. (a) Tier 1's unconditional flop cbet,
  tested against "only cbet with a made hand/draw": unconditional wins
  clearly (-1.11 vs -9.90 bb/100 without rake) -- KEPT. (b) Re-tested calling
  a raise (narrow range, half the open VPIP) now that the postflop plan can
  actually defend a hand (draws + value-betting without initiative fixed the
  conditions that made v1's flatting a leak): +0.86 bb/100 (no rake) --
  ENABLED. Realistic rake (5%, capped 5bb) still costs roughly 7-15 bb/100 on
  top of this (unstable estimate, see the script's caveat), so the honest
  summary is: this strategy is roughly breakeven against this simulated
  population BEFORE rake, and mildly losing after it. It is not a proven
  winner -- it's the result of a disclosed, reproducible diagnostic process,
  not a guarantee.

  v7: an earlier session's notes claimed "0% of hole cards revealed" in this
  dataset, which shaped the whole VPIP-implied-range approach. That claim was
  WRONG -- it grepped for a PokerStars-text "shows" keyword against files
  that use the real PHH format's `sm` verb, and never matched. Re-checked
  directly: 703,629 real showdown ('sm') actions across the 1000 ps_nl25
  files, 346,606 (49%) with REAL, unmasked cards -- sitting parsed into
  `Hand.showdown` by phh_parser.py the whole time, just never persisted
  downstream. Extracted into
  PokerDom_Microlimits_Analysis/data/processed/showdowns.parquet (284,622
  rows; scripts/extract_showdowns.py, which also documents the two real
  selection biases in this data: only-reaches-showdown and
  show-or-can-still-muck). Comparing real showdown-conditioned opening hands
  against the raw-equity-percentile OPEN ranges above: the percentile
  technique only covered 64-76% of real showdown-opener hands by position.
  Consistently missing, at meaningful real frequency (1-3.5%): KQo, KJo, QJo,
  ATo, QTo, JTo, and small pairs (66/55/44/33) at the tighter positions --
  exactly the well-known real limitation of ranking by raw equity vs a random
  hand (it undervalues offsuit broadways, whose value is postflop
  playability/domination, and small pairs, whose value is set-mining implied
  odds -- neither shows up in a raw all-in-equity number). Added these as
  REAL_DATA_RANGE_ADDITIONS, unioned into each position's OPEN range (a
  floor, not a ceiling -- see that constant's comment for why this doesn't
  overclaim what showdown-biased data can support). Result: +5.25 bb/100
  (no rake, 95% CI +/-2.49 -- the first result clearly above zero, not just
  within noise) and -1.09 bb/100 (with realistic rake, CI +/-2.30 -- back to
  breakeven, no longer clearly losing).

  Separately, research into published microstakes strategy (BlackRain79
  and others) confirmed rather than changed the existing design: semi-bluff
  raising draws is explicitly NOT recommended at NL10-and-below specifically
  BECAUSE calling stations have no fold equity to give up -- exactly this
  bot's call-only (never raise) draw handling, and exactly why the
  unconditional-flop-cbet A/B test above still won even though nothing else
  bluffs.

  v8: re-ran the same real-data-floor technique from v7, but for the CALL
  range (players who called facing one raise and reached showdown, not
  openers). The gap was far bigger here: the synthetic "half the open VPIP"
  call range covered only 14-36% of real callers' shown hands (vs 64-76% for
  the open range). Did NOT take the real distribution wholesale -- its
  85%-coverage set is ~45-50% of the ENTIRE hand space, which mostly reflects
  which speculative hands (suited connectors, small pairs) survive to
  showdown *when they hit*, not how often they're actually called with; using
  it directly would hugely overstate the true calling range. Applied the same
  >=1%-real-frequency floor as v7 instead (REAL_DATA_CALL_RANGE_ADDITIONS,
  14-26 hands added per position). Result: -0.20 bb/100 with rake (CI
  +/-2.43 -- indistinguishable from exactly breakeven) and +5.21 bb/100
  without (CI +/-2.54, unchanged from v7 within noise).

  v9: widened VALUE_3BET from {AA,KK,QQ,AKs,AKo} to also include {JJ,TT,AQs,
  AQo} (Tier 2's own hypothesis: this population barely 3-bets and probably
  under-punishes it) -- more preflop-only fold equity is specifically valuable
  against rake, since "no flop no drop" means a pot that ends preflop pays no
  rake at all. Facing a 3-bet or deeper, kept the ORIGINAL tight set
  (PREMIUM_VS_3BET stayed {AA,KK,QQ,AKs,AKo} -- going another street deep with
  JJ/TT/AQ against real aggression wasn't worth testing). Result: -1.57 bb/100
  with rake, +5.64 without -- both within the same CI band as v8, i.e. NOT a
  distinguishable change, just noise at this sample size. Kept anyway since
  it's theoretically sound and doesn't measurably hurt.

  Where v7-v9 left things: all landed in the same statistical neighborhood --
  roughly breakeven with rake (-0.2 to -1.6 bb/100, CI ~+/-2.3-2.6) and
  clearly positive without it (+5.2 to +5.6 bb/100). Further single-rule
  preflop-range tweaks weren't moving the needle past the noise floor.

  v10: added the ONE deliberately-scoped piece of opponent modeling this bot
  has -- see LOOSE_ARCHETYPES and has_any_pair_or_better. When facing a bet
  from a seat known to be Loose-passive/Station/Maniac, loosen the calling
  bar from top-pair-or-better to ANY pair or better. This is Tier 3 of the
  guide's own conclusion made actionable ("не переигрывайте постфлоп против
  Nit/TAG; играйте активнее до ривера против Station/Maniac") -- these three
  archetypes are also ~58% of the real population (Loose-passive 28.8% +
  Station 19.7% + Maniac 9.4%, from label_archetypes on the full dataset), so
  a rule that only fires against them still fires often. Tested with
  scripts/simulate_abc_bot.py's ground-truth-archetype ceiling test (the live
  app would use the session dossier's ESTIMATED style instead -- see
  choose_abc_action's docstring): opponent-unaware baseline was -3.19 bb/100
  (with rake); opponent-aware was +12.86 bb/100 -- a +16.05 bb/100 delta, far
  beyond the ~+/-2.5 CI noise floor that swallowed every earlier tweak. Made
  it the default. Final numbers: **+11.03 bb/100 with real rake (95% CI
  +/-2.54) and +22.59 bb/100 without (CI +/-2.85)** -- both now clearly,
  robustly above zero, and in the same range as the guide's own cited
  benchmark (BlackRain79: 10-20 bb/100 for a winning micro-stakes reg).

  Why this one rule mattered so much more than the preflop-range tweaks: the
  earlier tweaks all touched WHICH HANDS enter a pot, a relatively small
  lever (opening/calling frequency differences of a few percentage points).
  This one touches HOW OFTEN A GOOD HAND GETS TO REALIZE ITS VALUE against
  the specific majority of the population that bets/raises without one --
  a single conditional check with a much bigger multiplier, because it fires
  on every postflop street against most of the table, not just at one
  preflop decision point.

  v11: asked "does the bot account for multiway pots?" -- it didn't, at all;
  every range/threshold applied identically whether 1 or 4 opponents were
  live. Added MULTIWAY_AWARE, gating three standard real-poker adjustments to
  heads-up only (2+ live opponents = multiway): (1) the flop cbet-with-air
  only fires heads-up, made-hand-only otherwise; (2) the any-pair-or-better
  loosening vs a known loose archetype only applies heads-up; (3) facing a
  raise already called by someone else, only continue with VALUE_3BET-tier
  hands, not the wider call range. All three are standard, well-founded
  tightening moves in general poker theory. Tested anyway (habit, by this
  point) rather than assumed: A/B, both variants otherwise identical to v10.
  Result: WORSE with multiway-tightening on -- +4.34/+10.96 bb/100 (with/
  without rake) vs +11.03/+22.59 without it, a real drop (~7-12 bb/100, both
  directions moving the same way, not just one noisy run). Shipped
  MULTIWAY_AWARE = False. The likely reason, and a genuinely interesting
  finding about THIS specific population rather than poker in general:
  standard multiway-tightening assumes the other players in the pot are more
  likely to have a real hand simply because there are more of them -- but
  when ~58% of the population is Loose-passive/Station/Maniac (see the v10
  note), "more players in the pot" mostly means "more weak/wide ranges in
  the pot," not "more danger." Tightening preemptively against a population
  that's mostly weak regardless of pot size gave up more value (missed cbets
  that would still have gotten through, missed calls against still-weak
  multiway ranges) than it saved. The feature and its tests are kept in the
  code (see LOOSE_ARCHETYPES / MULTIWAY_AWARE and the multiway tests in
  tests/test_abc_bot.py, which monkeypatch it on to verify the mechanism
  works) -- just shipped off, because "theoretically sound" and "measured
  positive against this specific opposition" turned out to be different
  things, and the whole point of this file is testing before assuming.

  v12: after the 2026-07-30 dataset expansion (1000 -> 4379 PokerStars
  files, 3.56M hands), the archetype population mix was refreshed
  (backend/sessions/live_dynamics.py's ARCHETYPE_POPULATION_WEIGHTS) --
  Loose-passive+Station+Maniac went from 57.9% to 68.5% of the labeled
  population. Since the LOOSE_ARCHETYPES opponent-aware rule is precisely
  the exploit of that subset, re-ran the same 80k-hand simulation with no
  other code change: **+15.05 bb/100 with real rake (95% CI +/-2.72), +24.86
  without (CI +/-2.91)** -- both up from v11's +12.89/+21.36. The single
  biggest lever in this whole file (v10's opponent-aware rule) got more
  valuable purely because the population turned out to be even more skewed
  toward exactly what it exploits, not because of any new code.

  v13: every prior opponent-aware measurement (v10 onward) fed this function
  the ground-truth archetype the ML bot was actually seated with -- a ceiling
  test, since the live app can only ever see backend/dossier.py's noisy,
  no-minimum-hands-gate in-session ESTIMATE, not the true label. Ran a
  three-way comparison (scripts/simulate_abc_bot.py --dossier-realism) to
  check how much of that ceiling survives under realistic conditions:
  unaware baseline -2.44 bb/100, ground-truth ceiling +14.51, dossier estimate
  +13.42 (95% CIs all overlap). The dossier-based version **retains ~94% of
  the ceiling gain** -- the rule doesn't depend on cheating to work; a
  realistic in-session read captures nearly all of the value.

Full rule set (every decision point, quoted plainly so it can be read as a
strategy card, not just inferred from code):

  PREFLOP, unopened:
    - BB, action folds/limps to you: check (free).
    - Otherwise: raise to 2.5bb with a hand in your position's OPEN range
      (UTG 13.9% / MP 16.5% / CO 21.6% / BTN 26.6% / SB 24.5%, by VPIP-implied
      percentile -- the technique from the guide -- UNION real-showdown-data
      additions, see REAL_DATA_RANGE_ADDITIONS and the v7 note above). Else
      fold.

  PREFLOP, facing a raise (any number of raises deep):
    - {AA, KK, QQ, AKs, AKo}: raise (value) to 3x the previous bet if this is
      the first raise faced, or just call that same set if already 3-bet or
      deeper (going a 5th/6th bet deep on a static hand-strength bot isn't
      worth the added complexity).
    - Else, if facing exactly one raise: call with a hand in your position's
      CALL range (half the open VPIP, e.g. UTG ~7% / BTN ~13.3% -- the
      tighter, stronger half of what you'd open).
    - Else: fold.

  POSTFLOP, checked to (to_call <= 0), any street:
    - Bet ~55% pot if your hand is top-pair-or-better (value bet) --
      regardless of whether you had preflop initiative.
    - Flop ONLY, additionally: bet ~55% pot with ANY hand if you had preflop
      initiative and haven't bet yet this street (the one Tier-1 fold-equity
      cbet -- confirmed by A/B test to be worth keeping).
    - Otherwise: check. "Don't auto-barrel" means don't fire without a hand
      on the turn/river -- it does not mean never bet a strong hand.

  POSTFLOP, facing a bet, any street:
    - Call with top-pair-or-better (rank-count based -- see
      has_top_pair_or_better -- now including made straights/flushes).
    - Else, IF the specific opponent who bet is a known Loose-passive/
      Station/Maniac (see LOOSE_ARCHETYPES): call with ANY pair or better
      (has_any_pair_or_better) instead of the stricter top-pair bar. This is
      the bot's one deliberate piece of opponent modeling -- see the v10 note
      above for why it's worth so much more than everything else combined.
    - Else call with a real flush or open-ended-straight-ish draw IF the
      price is at least as good as the draw's rough continue-equity
      (~35% w/ two cards to come on the flop, ~19% w/ one card on the turn --
      see should_call_with_draw). Never on the river (no card left to come).
    - Else fold. Never raise postflop.

  Known, disclosed simplifications (not bugs, just where "simple" stops):
    - Hand-strength/draw detection is rank-count and rank-window based, no
      full 7-card evaluator -- doesn't distinguish open-ended draws from
      gutshots, doesn't handle backdoor draws, doesn't read board texture
      beyond what's needed for these two checks.
    - Bet sizing is always ~55% pot / a single fixed preflop size -- no
      sizing-for-effect, no polarization, no adjusting for stack depth.
    - Opponent modeling is limited to the one postflop-calling-bar rule
      above -- ranges, sizing, and the flop cbet stay identical regardless
      of archetype, unlike the live practice app's
      dossier-aware EV panel.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
sys.path.insert(0, str(ANALYSIS_ROOT))

from src.analysis.hand_rankings import RANKS, compute_hand_rankings
from src.analysis.implied_range import implied_range

from backend.bots.behavior_clone import _seat_position
from backend.engine.hand import Hand

OPEN_VPIP_BY_POSITION = {"UTG": 0.139, "MP": 0.165, "CO": 0.216, "BTN": 0.266, "SB": 0.245}
CALL_VPIP_BY_POSITION = {pos: vpip * 0.5 for pos, vpip in OPEN_VPIP_BY_POSITION.items()}

# Real hands from data/processed/showdowns.parquet (284,622 genuine revealed
# hole cards -- PokerDom_Microlimits_Analysis/scripts/extract_showdowns.py):
# for each position, hands real players opened with and reached showdown
# with at >=1% frequency, that the raw-equity-percentile OPEN range above
# doesn't include. This is a well-known, now-empirically-confirmed limitation
# of ranking hands by raw all-in equity vs a random hand: it systematically
# undervalues offsuit broadways (KQo/KJo/QJo/ATo -- their value is postflop
# playability/domination, not raw equity) and small pairs (set-mining implied
# odds), relative to how real players actually value and play them. NOT a
# claim that this makes the range "complete" -- showdown data is itself
# biased toward stronger/winning hands (see extract_showdowns.py's
# docstring) -- just a floor: if a hand shows up this often even in the
# smaller, biased "reached showdown" sample, it's definitely part of the
# real range, so union it in rather than let a percentile artifact exclude it.
REAL_DATA_RANGE_ADDITIONS = {
    "UTG": {"KQo", "ATo", "KJo", "66", "KQs", "QJo", "55", "44"},
    "MP": {"KQo", "ATo", "KJo", "QJo", "44", "33"},
    "CO": {"KQo", "QJo", "44", "QTo"},
    "BTN": {"QJo", "QTo", "JTo"},
    "SB": {"QJo", "JTo"},
}

# Same real-data-floor technique, applied to the CALL range: real showdown
# data for players who CALLED (not opened) facing exactly one raise showed
# only 14-36% coverage by the synthetic "half the open VPIP" range -- a much
# bigger gap than the open range had. IMPORTANT: did NOT just take the real
# distribution wholesale (its 85%-coverage set is ~45-50% of the entire hand
# space -- an unusably wide "range" that mostly reflects which speculative
# hands survive to showdown *when they hit*, not how often they're actually
# called with; see extract_showdowns.py's showdown-selection-bias caveat).
# Applied the same conservative floor as the open range instead: only hands
# at >=1% real frequency get added, same reasoning as REAL_DATA_RANGE_ADDITIONS.
REAL_DATA_CALL_RANGE_ADDITIONS = {
    "UTG": {"A8o", "A7s", "J9o", "KQo", "A7o", "JTo", "66", "QTo", "22", "A3o", "K9o", "33",
            "ATo", "JTs", "KTs", "A9o", "44", "A5o", "KTo", "A2o", "KJo", "QJs", "KJs", "T9o", "QJo", "55"},
    "MP": {"A8o", "KQo", "A7o", "JTo", "66", "QTo", "22", "33", "ATo", "JTs", "T9s", "KQs",
           "44", "A5o", "KTo", "KJo", "QJs", "T9o", "QJo", "55"},
    "CO": {"A8o", "A6s", "98s", "KQo", "JTo", "66", "QTo", "22", "QTs", "33", "ATo", "JTs",
           "T9s", "KQs", "44", "AJs", "KTo", "KJo", "T9o", "QJo", "55"},
    "BTN": {"ATs", "JTs", "KTs", "QTo", "22", "KQo", "KJo", "KQs", "QTs", "33", "44", "ATo",
            "JTo", "66", "QJo", "55"},
    "SB": {"AJs", "JTs", "QTo", "22", "KQo", "KJo", "KQs", "33", "44", "ATo", "JTo", "66", "QJo", "55"},
}

OPEN_SIZING_BB = 2.5  # "2.5-3bb" in the guide; picking the low end, fixed, as the one sizing Tier 1 calls for
THREEBET_MULTIPLIER = 3.0  # standard "make it 3x" value 3-bet sizing

VALUE_3BET_TIGHT = {"AA", "KK", "QQ", "AKs", "AKo"}
VALUE_3BET_WIDE = VALUE_3BET_TIGHT | {"JJ", "TT", "AQs", "AQo"}
# A/B-test switch: Tier 2 found this population barely 3-bets (2-5% of raise
# responses) and probably under-punishes it -- flagged there as an unproven
# hypothesis, not a validated finding. Widening the value-3-bet range adds
# preflop-only fold equity, which is specifically valuable against rake
# ("no flop no drop" -- a preflop-only win pays zero rake).
USE_WIDE_VALUE_3BET = True
VALUE_3BET = VALUE_3BET_WIDE if USE_WIDE_VALUE_3BET else VALUE_3BET_TIGHT
PREMIUM_VS_3BET = VALUE_3BET_TIGHT  # facing a 3-bet+, stay tight regardless -- going deeper with JJ/TT/AQ vs real aggression isn't worth it

# A/B-test switch for scripts/simulate_abc_bot.py: Tier 1 says "one flop cbet
# on most flops," unconditionally. If this population doesn't fold enough to
# a FLOP bet specifically (Tier 2's fold-equity numbers are about PREFLOP
# raises, not flop continuation bets), firing 100% of flops with total air
# could itself be a leak. Flip to False to cbet only with a made hand or a
# real draw instead, and compare. Tested: unconditional cbet wins clearly
# (-1.11 bb/100 vs -9.90 bb/100 without rake, 80k hands each) -- keep True.
UNCONDITIONAL_FLOP_CBET = True

# A/B-test switch: v3 removed calling a raise entirely (raise-or-fold only)
# because it was a "fit or fold" leak under the OLD postflop plan (no draws,
# no value-betting without initiative). Now that both are fixed, re-test
# whether a narrow call (CALL_VPIP_BY_POSITION, half the open range) adds EV
# back by seeing more flops with a plan that can actually defend them.
ALLOW_CALLING_RAISES = True

# A/B-test switch: nothing in this bot previously distinguished a heads-up
# pot from a 5-way one -- the same ranges/thresholds applied regardless of
# how many opponents were live. Real strategy universally tightens in
# multiway pots (top pair is much weaker against 2+ opponents; a flop cbet
# with air has far less fold equity against multiple players; cold-calling a
# raise that's already been called once is worse odds than isolating
# heads-up). MULTIWAY_AWARE gates three things when 2+ opponents are live:
# (1) the unconditional flop cbet only fires heads-up, made-hand-only
# otherwise; (2) the loosened any-pair-or-better call vs a known loose
# archetype only applies heads-up; (3) facing a raise already called by
# someone else, only continue with VALUE_3BET-tier hands, not the wider
# call range.
MULTIWAY_AWARE = False

_rankings_cache = None
_open_range_cache: dict[str, set] = {}
_call_range_cache: dict[str, set] = {}


def _ranges():
    global _rankings_cache, _open_range_cache, _call_range_cache
    if _rankings_cache is None:
        _rankings_cache = compute_hand_rankings()
        _open_range_cache = {
            pos: set(implied_range(vpip, _rankings_cache)) | REAL_DATA_RANGE_ADDITIONS.get(pos, set())
            for pos, vpip in OPEN_VPIP_BY_POSITION.items()
        }
        _call_range_cache = {
            pos: set(implied_range(vpip, _rankings_cache)) | REAL_DATA_CALL_RANGE_ADDITIONS.get(pos, set())
            for pos, vpip in CALL_VPIP_BY_POSITION.items()
        }
    return _open_range_cache, _call_range_cache


def _hand_notation(hole: list[str]) -> str:
    r1, r2 = hole[0][0], hole[1][0]
    suited = hole[0][1] == hole[1][1]
    order = {r: i for i, r in enumerate(RANKS)}
    if r1 == r2:
        return r1 + r2
    hi, lo = (r1, r2) if order[r1] < order[r2] else (r2, r1)
    return f"{hi}{lo}{'s' if suited else 'o'}"


def _n_bets_or_raises_this_street(hand: Hand) -> int:
    return sum(1 for a in hand.actions if a.street == hand.street and a.action in ("bets", "raises"))


def _n_raises_preflop(hand: Hand) -> int:
    return sum(1 for a in hand.actions if a.street == "preflop" and a.action == "raises")


def _had_preflop_initiative(hand: Hand, seat: int) -> bool:
    preflop_raises = [a for a in hand.actions if a.street == "preflop" and a.action == "raises"]
    return bool(preflop_raises) and preflop_raises[-1].seat == seat


def _n_live_opponents(hand: Hand, seat: int) -> int:
    return sum(1 for s, p in hand.players.items() if s != seat and p.in_hand)


def _n_callers_since_last_raise_preflop(hand: Hand) -> int:
    """How many players have already called the current preflop raise before
    hero's turn -- a raise that's already been called once or more is a
    forming multiway pot, where a marginal cold-call has worse odds (less
    fold equity for hero to isolate, more opponents to beat to win)."""
    preflop = [a for a in hand.actions if a.street == "preflop"]
    last_raise_i = max((i for i, a in enumerate(preflop) if a.action == "raises"), default=None)
    if last_raise_i is None:
        return 0
    return sum(1 for a in preflop[last_raise_i + 1 :] if a.action == "calls")


_RANK_ORDER = "23456789TJQKA"


def _rank_counts(cards: list[str]) -> dict:
    counts: dict[str, int] = {}
    for c in cards:
        counts[c[0]] = counts.get(c[0], 0) + 1
    return counts


def _has_made_flush(hole: list[str], board: list[str]) -> bool:
    suit_counts: dict[str, int] = {}
    for c in hole + board:
        suit_counts[c[1]] = suit_counts.get(c[1], 0) + 1
    return any(n >= 5 for n in suit_counts.values())


def _has_made_straight(hole: list[str], board: list[str]) -> bool:
    ranks = {c[0] for c in hole + board}
    if {"A", "2", "3", "4", "5"} <= ranks:
        return True
    idxs = sorted(_RANK_ORDER.index(r) for r in ranks)
    for i in range(len(idxs) - 4):
        window = idxs[i : i + 5]
        if window[-1] - window[0] == 4:
            return True
    return False


def _has_flush_draw(hole: list[str], board: list[str]) -> bool:
    suit_counts: dict[str, int] = {}
    for c in hole + board:
        suit_counts[c[1]] = suit_counts.get(c[1], 0) + 1
    return any(n == 4 for n in suit_counts.values())


def _has_straight_draw(hole: list[str], board: list[str]) -> bool:
    """4 ranks spanning a 5-wide window (e.g. 6-7-8-9) -- doesn't distinguish
    open-ended (8 outs) from a gutshot (4 outs), a disclosed simplification
    that biases toward calling slightly wider draws than a precise count
    would justify."""
    ranks = {c[0] for c in hole + board}
    if len({"A", "2", "3", "4"} & ranks) >= 3 and "5" in ranks:
        return True
    idxs = sorted(_RANK_ORDER.index(r) for r in ranks)
    for i in range(len(idxs) - 3):
        window = idxs[i : i + 4]
        if window[-1] - window[0] <= 4:
            return True
    return False


# Rough continue-equity for a made draw, by how many cards are left to come --
# standard "4 outs per card ~ 8-9%" rule-of-thumb numbers (9-out draw), not a
# precise combinatorial calculation. Used only to gate a pot-odds call, never
# a raise -- a real ABC beginner isn't semi-bluff-raising draws.
DRAW_EQUITY_BY_STREET = {"flop": 0.35, "turn": 0.19}


def has_top_pair_or_better(hole: list[str], board: list[str]) -> bool:
    """"Top pair or better" now also covers made straights/flushes (an earlier
    version only checked paired ranks, so a made straight/flush that didn't
    also pair something was incorrectly treated as air -- a real, if less
    common, mis-fold). Full-house/quads are already caught by the two-pair-or-
    better / trips-or-better rank-count branches below."""
    if not board:
        return False
    if _has_made_flush(hole, board) or _has_made_straight(hole, board):
        return True
    counts = _rank_counts(hole + board)
    top_board_rank = max((c[0] for c in board), key=_RANK_ORDER.index)
    pair_ranks = [r for r, n in counts.items() if n >= 2]
    if not pair_ranks:
        return False
    if len(pair_ranks) >= 2:
        return True  # two pair or better
    r = pair_ranks[0]
    if counts[r] >= 3:
        return True  # trips+
    hole_ranks = (hole[0][0], hole[1][0])
    is_pocket_pair = hole_ranks[0] == hole_ranks[1]
    if is_pocket_pair and _RANK_ORDER.index(hole_ranks[0]) > _RANK_ORDER.index(top_board_rank):
        return True  # overpair to the board
    return r == top_board_rank  # top pair


def has_any_pair_or_better(hole: list[str], board: list[str]) -> bool:
    """Weaker than has_top_pair_or_better: ANY pair (including bottom pair),
    not just top-pair-or-an-overpair. Used only when the specific opponent
    who bet is a known loose/weak archetype (see LOOSE_ARCHETYPES) -- Tier 3
    of the guide found these archetypes bet/raise with weak ranges on every
    street, so the usual top-pair-or-better bar is needlessly tight against
    them specifically."""
    if not board:
        return False
    if _has_made_flush(hole, board) or _has_made_straight(hole, board):
        return True
    counts = _rank_counts(hole + board)
    return any(n >= 2 for n in counts.values())


# Tier 3 of the guide (data/reference/matchup_hand_ev_by_position.csv): these
# three archetypes continue/bet with a weak range on every street (Station
# calls a lot with little; Maniac and Loose-passive similarly don't fold
# their hand to their own aggression) -- concretely, "не переигрывайте
# постфлоп против Nit/TAG; играйте активнее до ривера против Station/Maniac."
# Nit/TAG/LAG bettors, by contrast, mean it -- keep the normal, stricter bar
# against them. This is the ONE way this bot's postflop plan is
# opponent-aware; everything else (sizing, ranges, cbet) stays identical
# regardless of who's at the table, to keep this a "simple" strategy, not a
# full opponent-exploitative one.
LOOSE_ARCHETYPES = {"Loose-passive", "Station", "Maniac"}


def _last_aggressor_this_street(hand: Hand) -> int | None:
    street_bets = [a for a in hand.actions if a.street == hand.street and a.action in ("bets", "raises")]
    return street_bets[-1].seat if street_bets else None


def should_call_with_draw(hole: list[str], board: list[str], street: str, to_call: float, pot_before: float) -> bool:
    """Pot-odds-aware draw continuation: call a bet with no made hand yet if
    hero holds a real flush/straight draw AND the price is at least as good
    as the draw's rough continue-equity. River has no card left to come, so
    draws never justify a call there -- only a made hand does."""
    if street not in DRAW_EQUITY_BY_STREET:
        return False
    if not (_has_flush_draw(hole, board) or _has_straight_draw(hole, board)):
        return False
    if to_call <= 0:
        return False
    pot_odds_needed = to_call / (pot_before + to_call)
    return pot_odds_needed <= DRAW_EQUITY_BY_STREET[street]


def choose_abc_action(
    hand: Hand, seat: int, opponent_archetypes: dict[int, str] | None = None
) -> tuple[str, float | None]:
    """`opponent_archetypes`: optional {seat: archetype} for the OTHER seats
    at the table. Only used to loosen the postflop calling bar against a
    known loose/weak archetype (see LOOSE_ARCHETYPES) -- everything else in
    this bot ignores it entirely. In the live practice app this would come
    from each seat's session dossier (`dossier.style`, an estimate); the
    simulation script can also pass the ground-truth archetype to measure the
    ceiling of what opponent-awareness is worth before dossier noise."""
    open_ranges, call_ranges = _ranges()
    player = hand.players[seat]
    legal = hand.legal_actions(seat)
    to_call = legal["call_amount"]
    notation = _hand_notation(player.hole_cards)

    if hand.street == "preflop":
        position = _seat_position(hand, seat)
        n_raises = _n_raises_preflop(hand)

        if n_raises == 0:
            if to_call <= 0:
                return ("check", None)
            open_range = open_ranges.get(position)
            if open_range and notation in open_range:
                amount = hand.big_blind * OPEN_SIZING_BB
                amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
                return ("raise", amount)
            return ("fold" if to_call > 0 else "check", None)

        if n_raises >= 2:
            if notation in PREMIUM_VS_3BET:
                return ("call", None)
            return ("fold", None)

        # Facing exactly one raise.
        if notation in VALUE_3BET:
            amount = hand.current_bet * THREEBET_MULTIPLIER
            amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
            return ("raise", amount)
        # ALLOW_CALLING_RAISES: earlier versions found calling a raise (with
        # ANY range) under a fit-or-fold postflop plan (no draws, no value
        # betting without initiative) cost -74 bb/100 -- a free roll for
        # whoever has initiative. That postflop plan has since been fixed
        # (draws + pot odds, value bets without initiative too); this flag
        # re-tests whether a narrow call (half the open range) is safe again.
        # MULTIWAY_AWARE: if someone already called this raise, it's already a
        # forming multiway pot -- worse odds to cold-call marginal hands into,
        # so only the wide call range applies heads-up (no callers yet).
        already_multiway = MULTIWAY_AWARE and _n_callers_since_last_raise_preflop(hand) > 0
        if ALLOW_CALLING_RAISES and not already_multiway:
            call_range = call_ranges.get(position)
            if call_range and notation in call_range:
                return ("call", None)
        return ("fold", None)

    # postflop
    had_initiative = _had_preflop_initiative(hand, seat)
    n_bets = _n_bets_or_raises_this_street(hand)
    made = has_top_pair_or_better(player.hole_cards, hand.board)
    pot_before = sum(p.total_contributed for p in hand.players.values())
    is_multiway = MULTIWAY_AWARE and _n_live_opponents(hand, seat) >= 2

    if to_call <= 0:
        # "Don't auto-barrel" means don't keep firing without a hand -- it does
        # NOT mean give up betting a genuinely strong hand. ANY street, with or
        # without initiative, gets a value bet if hero's hand qualifies as
        # top-pair-or-better (checking down every made hand reached without
        # initiative was a measured -51.79 bb/100 leak, since fixed). The flop
        # additionally gets one cbet with NO hand at all when hero had preflop
        # initiative, IF UNCONDITIONAL_FLOP_CBET is on (Tier 1's literal rule;
        # see the module-level flag to A/B test whether this population folds
        # enough to a flop bet specifically for that to pay for itself) AND
        # it's heads-up -- MULTIWAY_AWARE drops the free-roll cbet against
        # 2+ opponents, where fold equity is much lower.
        cbet_with_air = UNCONDITIONAL_FLOP_CBET and had_initiative and hand.street == "flop" and n_bets == 0
        if is_multiway:
            cbet_with_air = False
        should_bet = made or cbet_with_air
        if should_bet and n_bets == 0:
            amount = pot_before * 0.525
            amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
            return ("bet", amount)
        return ("check", None)

    if made:
        return ("call", None)

    if opponent_archetypes and not is_multiway:
        aggressor = _last_aggressor_this_street(hand)
        aggressor_archetype = opponent_archetypes.get(aggressor) if aggressor is not None else None
        if aggressor_archetype in LOOSE_ARCHETYPES and has_any_pair_or_better(player.hole_cards, hand.board):
            return ("call", None)

    if should_call_with_draw(player.hole_cards, hand.board, hand.street, to_call, pot_before):
        return ("call", None)
    return ("fold", None)
