"""ABC v21: a simple but COMPLETE decision tree, built on top of the published
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

  v14: two hypotheses read directly off PokerDom_Microlimits_Analysis's
  archetype tables, tested here rather than assumed:
    A1 (STEAL_WIDER_VS_NIT): archetype_vs_raise.csv shows Nit folds to a
    raise 90.3-93.1%, almost flat across every position -- so widen the open
    range (STEAL_VPIP_BY_POSITION, roughly +15pp of VPIP per position) when
    every live opponent still to act is a known Nit.
    A2 (SIZING_TARGET_ARCHETYPES): archetype_facing_bet.csv's "large" bucket
    shows fold% to a big bet scales with tightness (Nit 73-75%, TAG 66-72%)
    but barely moves for Station/Maniac (~52-62%, same as their fold% to
    smaller bets) -- so size value bets up (0.75 pot vs the standard 0.525)
    specifically against a known Nit/TAG, heads-up only.
  Clean same-seed A/B (only these two flags toggled, everything else
  identical): baseline +11.63 bb/100 with rake (CI +/-2.82) / +16.23 without
  (CI +/-2.95); A1+A2 +12.26 with rake (CI +/-2.79) / +23.05 without
  (CI +/-3.03). **With realistic rake -- the number that actually matters --
  the delta is +0.63 bb/100, inside the noise floor: not a demonstrated
  win.** Without rake the delta is +6.82, bigger than the combined CI and
  plausibly real. Working theory for the gap: A2's bigger sizing raises pot
  size specifically in hands that get called/reach showdown -- exactly the
  pots rake (5%, capped 5bb) taxes -- while A1's extra preflop-only folds
  should be rake-free ("no flop no drop") but aren't enough on their own to
  clear the noise floor. Left both rules ON (STEAL_WIDER_VS_NIT=True,
  SIZING_TARGET_ARCHETYPES={"Nit","TAG"}) since neither measured harmful and
  A1 in particular is theoretically sound even unproven at this sample size
  -- but don't report this pair as a confirmed win to anyone relying on the
  with-rake number.

  Separately, noted in passing: this session's baseline run (+11.63 bb/100,
  ground-truth archetypes, same seed=42 as v12/v13) measured BELOW v12/v13's
  own recorded ground-truth numbers (+15.05, +14.51) despite being nominally
  the same comparison. Also found and fixed, same session: backend/
  dossier.py's `_position_label` carried its own copy of the seat->position
  table truncated at 5 seats (KeyError/IndexError on any 6-8max hand -- this
  project's actual default table size), now imports behavior_clone.py's full
  8-seat table instead of re-duplicating it. Didn't chase down whether that
  bug (or something else) explains the baseline drift -- flagging as an open
  discrepancy rather than a resolved one; if the baseline number matters for
  future work here, re-verify it rather than trusting either old or new
  numbers blindly.

  v15: two more hypotheses off the same archetype tables:
    B1 (WIDER_3BET_VS_LOOSE): archetype_vs_raise.csv / archetype_facing_bet.csv
    show Maniac and Station continue facing aggression far more than average
    -- widen VALUE_3BET (add 99/88/AJs/AJo/KQs/KQo) specifically when the
    raiser hero is 3-betting is a known Maniac/Station.
    B2 (SIZE_UP_ON_TURN): archetype_facing_bet.csv shows small-bet fold%
    drops sharply on the turn specifically vs flop/river, across every
    archetype (Nit flop-small fold 39% vs turn-small fold 27%) -- since this
    bot only ever bets the turn for value, size up unconditionally there
    (reused BIG_VALUE_SIZING_POT_FRACTION rather than adding a third number).
  Same clean same-seed A/B discipline as v14 (only these two flags toggled,
  A1/A2 left on both sides): baseline +10.50 bb/100 with rake (CI +/-2.76) /
  +18.08 without (CI +/-2.99); B1+B2 +10.23 with rake (CI +/-2.77) / +17.57
  without (CI +/-2.94). **Delta: -0.27 with rake, -0.51 without -- both
  trivially inside the noise floor. A clean null result, not a win and not a
  loss.** (An earlier same-session comparison against v14's OLDER separately-
  recorded numbers suggested B1+B2 looked worse -- that comparison wasn't a
  controlled A/B, just two different runs; the baseline itself had drifted
  between them the same way v12/v13's numbers drifted from this session's
  v14 baseline, see that note above. Lesson reinforced: always re-run a
  same-session baseline before trusting a delta, never diff against an old
  recorded number.) Kept both rules ON, same reasoning as v14 (theoretically
  sound, measured neither harmful nor helpful) -- but this is now three
  archetype-table-derived hypotheses (A1, A2, B1+B2) that read as strong,
  simple wins on paper and measured as noise-or-worse in practice. Worth
  registering as a pattern, not just three isolated nulls: a population-level
  frequency table (X% fold to Y) doesn't automatically translate into bot-vs-
  bot EV the way it would against a human, because the OPPOSING side here is
  itself a fixed statistical model (CAT_FEATURES = street/position/archetype
  only, see behavior_clone.py) reacting to hero's bet in ways that may not
  decompose the way the raw population table suggests. Future archetype-
  table-derived rules should be treated as unproven until measured here, not
  assumed to transfer 1:1 -- which is exactly the discipline this file has
  followed throughout, just worth saying explicitly now that it's happened
  three times in a row.

  Follow-up, same session: user asked whether B1 and B2 might be individually
  real but canceling each other out when combined. Isolated each (same
  baseline, only one flag on at a time): B1 alone +10.65 with rake (CI
  +/-2.80) / +18.40 without (CI +/-3.02) -- delta +0.15 / +0.32 vs baseline,
  trivial, confirms B1 alone is also just noise, not masked by B2. B2 alone
  +12.66 with rake (CI +/-2.75) / +15.48 without (CI +/-2.92) -- delta +2.16
  with rake but -2.60 without, i.e. the sign FLIPS depending on rake. Neither
  delta clears its own combined CI, so still not a confirmed effect, but the
  flip is a real data point: consistent with the same rake-taxes-bigger-
  called-pots mechanism floated for A2 above, and a reminder that "B1+B2
  measured as ~0" can hide individually noisy, opposite-signed components
  rather than meaning "neither one does anything" -- worth remembering before
  concluding a null result means the underlying idea was wrong, vs. just
  underpowered at this sample size or entangled with rake in a way a single
  bb/100 number doesn't show.

  v16, C1 (ISO_RAISE_OVER_LIMPERS): unlike A2/B1/B2 (archetype-table-derived
  numbers), this one is a standard live-poker sizing convention -- isolate a
  limper for open-size + ~1bb per limper instead of the flat open size the
  bot used before. Clean same-seed A/B (only this flag toggled, A1/A2/B1/B2
  all ON both sides): baseline +10.83 bb/100 with rake (CI +/-2.75) / +17.54
  without (CI +/-2.91); C1 +12.97 with rake (CI +/-2.76) / +22.64 without
  (CI +/-2.99). **Delta +2.14 with rake (inside the combined ~+/-3.9 CI, not
  fully clearing it, but the largest with-rake point estimate of any single
  rule tested this session) and +5.10 without rake (exceeds the combined
  ~+/-4.2 CI -- the clearest without-rake result since A1+A2's original
  +6.82).** Kept ON. Notably this is the one rule this session that did NOT
  come from an archetype population table read cold -- it's textbook sizing
  theory, tested rather than assumed like everything else here -- and it's
  also the one with the cleanest result. Weak evidence for a pattern: rules
  grounded in how the BETTING STRUCTURE itself works (pot math, isolation
  odds) may transfer to this ML-bot population more reliably than rules
  inferred from population fold-frequency tables (see the v15 note on why
  those may not decompose the way raw frequencies suggest) -- one data point,
  not proven, but worth watching if more rules get tested here.

  v17, C2 (DONK_BLUFF_VS_TIGHT): PokerDom_Microlimits_Analysis's decision_
  points.py was extended this session to tag each postflop bet with whether
  the bettor had preflop initiative, producing archetype_facing_bet_by_
  initiative.csv for the first time -- new data, not previously available.
  It shows Nit/TAG/LAG fold to a donk bet/lead meaningfully more than to a
  same-sized cbet (Nit +13.6pp, TAG +9.3pp, LAG +6.0pp, on 60k-460k-row
  samples); Station/Maniac showed no real difference and were excluded. The
  bot previously only ever bluffed as an in-position flop cbet WITH
  initiative -- this adds a genuinely new behavior, a donk bluff with no
  hand at all, specifically when hero lacks initiative, is heads-up, and
  the single opponent is a known Nit/TAG/LAG. Clean same-seed A/B (only this
  flag toggled, A1/A2/B1/B2/C1 all ON both sides): baseline +14.71 bb/100
  with rake (CI +/-2.78) / +21.46 without (CI +/-2.95); C2 +17.04 with rake
  (CI +/-2.76) / +26.80 without (CI +/-2.98). **Delta +2.33 with rake
  (inside the combined ~+/-3.9 CI, same "suggestive but not fully clearing"
  pattern as C1) and +5.34 without rake (exceeds the combined ~+/-4.2 CI --
  real).** Kept ON; +17.04 bb/100 with rake is the highest single-rule
  with-rake result of the whole session. This complicates the v15/v16
  pattern-hunting: C2 IS archetype-frequency-table-derived (like A1/A2/B1/
  B2, which mostly measured as noise) but represents a NEW behavior rather
  than a range/sizing tweak on an existing action (like C1, which measured
  well) -- so on the "new behavior vs. parameter tweak" axis it groups with
  the winner (C1), not the data-source axis. Tentative revised read: what
  predicts a real result here isn't where the number came from, it's
  whether the rule changes WHAT the bot does (a new action in a spot it
  previously played the same way regardless) rather than HOW MUCH of
  something it already does (a wider range, a bigger bet). Two data points
  (C1, C2) now, still not proof -- but a more specific hypothesis than v16's
  original guess, worth testing again if a Tier D ever gets scoped.

  v18 (2026-08-07): user asked to actually settle whether v11's bundled
  MULTIWAY_AWARE (all three sub-rules toggled together, measured as hurting)
  was hiding one good rule under two bad ones. Split the single flag into
  three independent ones -- MULTIWAY_NARROW_CALL_RANGE, MULTIWAY_DISABLE_
  AIR_CBET, MULTIWAY_DISABLE_LOOSE_CALL -- and A/B'd each alone against the
  same fresh baseline (+12.26 bb/100 with rake, CI +/-2.82; this baseline is
  itself post monster-pot-fix, see behavior_clone.py, so not comparable to
  pre-2026-08-07 numbers above). All three individually:
    - disable air cbet in multiway: +4.32 (delta -7.94, clearly hurts --
      the unconditional flop cbet is one of the strategy's biggest positive
      levers per v6, and 3+-way flops are common enough that restricting it
      costs a lot)
    - disable the v10 loose-archetype call-loosening in multiway: +6.35
      (delta -5.91, clearly hurts -- v10 is THE single biggest lever in this
      file, and per v11's own finding this population is weak/loose
      regardless of table size, so restricting the exploit specifically in
      multiway throws away most of its value there too)
    - narrow the call range when a raise is already called by someone else:
      +8.30 (delta -3.96, borderline -- inside/at the edge of the combined
      CI with rake, +1.04 without rake i.e. flat) -- closest to noise of the
      three, but still not a demonstrated win
  **Conclusion: no hidden winner. Bundling didn't mask anything -- all three
  sub-rules are individually neutral-to-harmful, confirming v11's original
  finding was correct for the right reason, not just correct on average.**
  All three flags shipped False (unchanged from v11). If multiway-specific
  strategy is revisited, the productive direction per this file's own C1/C2
  pattern-hunting is probably a NEW behavior for multiway pots specifically
  (not yet scoped), not further restricting existing ones.

  v19 (2026-08-07): two more tests, user-requested. (a) HERO_PROGRESSIVE_
  POT_DAMPING -- behavior_clone.py's 2026-08-07 monster-pot fix only touched
  the ML opponent bots; hero's OWN value-bet sizing was never covered, still
  a flat ~55% pot regardless of how big the pot already was. Added the same
  damping shape hero-side (starts softening past 8bb pot, floors at 8% pot by
  30bb pot). Clean isolated A/B, same seed, both arms otherwise identical:
  without damping +12.21 bb/100 with rake (CI +/-2.83) / +23.01 without (CI
  +/-3.08); with damping +21.78 / +35.33 (CI +/-3.05 / +/-3.31). Delta +9.57
  / +12.32, both several times the combined CI -- a real, large effect, and
  the biggest single lever measured since v10. Notably the monster-pot RATE
  barely moved (20.1% -> 19.8%, within noise of a rate this size) -- this
  fix doesn't stop pots from ballooning, it stops hero from overbetting
  chips into ones that already have. Shipped True.
  (b) SIZE_UP_PREMIUM_OPENS -- user's hypothesis: open premium hands
  (VALUE_3BET_TIGHT) bigger, scaled by limper count, since a hand that plays
  well multiway benefits less from folding out limpers than one that wants
  it heads-up for stack-off value. Implemented as a flat +1.5bb bonus on the
  standard 2.5bb open. Re-tested AFTER (a) above, both arms with hero damping
  on, so this is the clean comparison: without +21.78 with rake (CI +/-3.05)
  / +35.33 without (CI +/-3.31); with +23.54 / +34.57 (CI +/-3.03 / +/-3.33).
  Delta +1.76 with rake, -0.76 without -- inside the combined CI both ways,
  sign even flips between the two rake conditions on the same seed. Not a
  demonstrated effect. Shipped False, per this file's standing policy of not
  carrying unproven complexity (same call made for behavior_clone.py's
  reverted 4th monster-pot refinement the same day).

  v20 (2026-08-07 pm): follow-up on the monster-pot investigation -- see
  behavior_clone.py's "Monster-pot fix, follow-up" docstring section for the
  full diagnosis (scripts/diagnose_monster_pots.py classified the remaining
  ~20% of monster pots: 84.9% turned out to be moderate 1-2-raises-per-street
  escalation compounding across several streets, not the suspected multiway-
  calling-without-a-raise pattern, which was only 1.4%). Tightened
  HERO_POT_DAMPING_START_BB/FULL_BB/FLOOR_FRAC the same way as behavior_
  clone.py's matching constants (8/30/0.08 -> 5/18/0.05), since this hero-
  side damping uses the identical mechanism. Measured together with the
  ML-bot-side tightening, 80k hands, same seed: monster-pot rate 19.87% ->
  12.02%/11.82% (with/without rake), bb/100 excl. monster pots +21.78 ->
  +61.30 with rake (CI +/-3.05 vs +/-3.98) / +35.33 -> +78.04 without (CI
  +/-3.31 vs +/-4.31) -- both moved substantially in the right direction
  together, no rate-vs-magnitude tradeoff. Honest caveat: ~12% of hands
  still exceed 50bb, and at this table's 100bb effective stack depth some
  real portion of that is likely legitimate deep-stack variance rather than
  a residual bug -- the 50bb threshold was always a coarse flag, not a
  strict bug definition.

  Same session, immediate follow-up: tightened behavior_clone.py's
  SUPPRESS_RAISE_WHEN_MIN_RAISE_LARGE thresholds too (ML-bot-only mechanism,
  no hero-side equivalent needed at the time -- hero didn't raise postflop
  yet [that changed in v22 below, gated to a strict very-strong-hand subset
  clamped by legal["max_raise_to"], not the open-ended re-raise pattern this
  suppression targets] and preflop sizing isn't gated by this legal-action
  suppression). Real further drop,
  monster-pot rate 12.02%/11.82% -> 11.14%/11.09%; bb/100 excl. monster pots
  flat within noise both ways (+61.30->+63.57 with rake, +78.04->+77.03
  without). See behavior_clone.py's "third pass" docstring section for the
  full numbers -- kept since it's a real rate improvement at no cost.

  v21 (2026-08-08, overnight): tested a squeeze-specific preflop hypothesis
  (widen the 3-bet range and/or size up when facing a raise that's already
  been called by someone else, on the theory that dead money justifies it) --
  SQUEEZE_WIDER_RANGE and SQUEEZE_SIZE_UP_PER_CALLER flags, see their
  comments above. Initial 80k-hand tests leaned consistently positive but
  never cleared the combined CI (+4.64/+5.31 wider-alone, +0.55/+1.86
  size-alone, +2.93/+5.74 combined). Re-tested at 300k hands per side for
  real statistical power: delta shrank to +0.87/+1.61, cleanly inside the
  ~2.9-3.05 combined CI -- confirms the 80k signal was sampling noise, not a
  suppressed real effect. Shipped both False. (Unrelated: this 300k run also
  hit a real ~4.6-hour stall on one 80k-equivalent pass, later traced to the
  machine sleeping/throttling mid-run with no `caffeinate` guard -- see
  behavior_clone.py's had_initiative changelog entry for the fix applied to
  all subsequent long runs that night.)

  Separately (no hero-side code change, ML-bot-only): behavior_clone.py
  gained a had_initiative feature this same night, after a training/serving
  skew bug was found and fixed (full story in that file's docstring -- worth
  reading, it's the kind of "the number looked too good" catch this file's
  own history keeps coming back to). Net effect on hero: monster-pot rate
  rose 11.14%/11.09% -> 12.68%/12.72% (real, disclosed tradeoff for a real
  realism improvement), bb/100 excl. monster pots unchanged within noise.

  2026-08-11: v9, v14 (A1+A2), and v15 (B1+B2) were all shipped True back
  when they were first tested, on "theoretically sound, doesn't measurably
  hurt" reasoning rather than a demonstrated with-rake win (unlike v19/
  v21+, which were properly shipped False when unconfirmed) -- never
  re-tested at real power the way SQUEEZE_WIDER_RANGE (v21) was, despite
  being live in the bot the whole time. Closed that gap: re-ran all five
  of that era's flags (v9, v14, v15, v16 C1, v17 C2) at 500k hands/arm
  (scripts/simulate_abc_bot.py --flag-confirm all), same real-rake/ground-
  truth-archetype discipline as every other test in this file. Real result:
    v9  USE_WIDE_VALUE_3BET:  delta +0.80 (CI +/-1.57/+1.57, combined ~2.22)
    v14 A1+A2:                delta +0.67 (CI +/-1.57/+1.56, combined ~2.21)
    v15 B1+B2:                delta +1.62 (CI +/-1.57/+1.56, combined ~2.21)
    v16 C1:                   delta +4.88 (CI +/-1.53/+1.57, combined ~2.19)
    v17 C2:                   delta +3.40 (CI +/-1.56/+1.57, combined ~2.21)
  v16 and v17 NOW CLEAR the combined CI at real power -- genuinely
  confirmed, not just "kept on faith." v9/v14/v15 still don't, even at 6x
  the original sample size. Sanity-checked against their own original 80k
  numbers for a sign-consistency read (not a rigorous test, just a cheap
  extra signal): v9 flipped sign (-1.57 -> +0.80) and v15 flipped sign
  (-0.27 -> +1.62) between independent runs -- the signature of bouncing
  around a true zero, not a small real effect. v14 did NOT flip (+0.63 ->
  +0.67, same sign, similar magnitude across two independent samples) --
  the one candidate that might reward an even bigger re-test someday, if
  revisited (deferred, not run).

  This closes the loop on the v15 pattern-hunting note above (and the C1/
  C2 follow-up on it): of these five, the two that confirmed as REAL
  (C1 -- a sizing convention, and C2 -- a genuinely new bluffing behavior)
  are exactly the two that note already flagged as the stronger pattern;
  the three archetype-frequency-table-derived RANGE-WIDENING theories
  (A1+A2, B1+B2, and now v9's value-3bet widening too) failed a THIRD
  time, even at 6x the sample size. Three theory generations of "just
  widen a range because a population table says so" have now measured as
  noise-or-worse; "change what the bot DOES, not just how wide a range
  it plays" is the more consistently productive direction this file's own
  history points to.

Full rule set (every decision point, quoted plainly so it can be read as a
strategy card, not just inferred from code):

  PREFLOP, unopened:
    - BB, action folds/limps to you: check (free).
    - Otherwise: raise to 2.5bb with a hand in your position's OPEN range
      (UTG 13.9% / MP 16.5% / CO 21.6% / BTN 26.6% / SB 24.5%, by VPIP-implied
      percentile -- the technique from the guide -- UNION real-showdown-data
      additions, see REAL_DATA_RANGE_ADDITIONS and the v7 note above), OR
      (v29, ISO_WIDER_RANGE_OVER_LIMPERS, untested) the same widened range
      STEAL_WIDER_VS_NIT uses if at least one player has already limped in
      -- a limper has shown a weak/speculative hand, isolate them wider,
      not just for more money (see ISO_RAISE_OVER_LIMPERS just below).
      Else fold.

  PREFLOP, facing a raise (any number of raises deep):
    - {AA, KK, QQ, AKs, AKo}: raise (value) to 3x the previous bet if this is
      the first raise faced, or just call that same set if already 3-bet or
      deeper (going a 5th/6th bet deep on a static hand-strength bot isn't
      worth the added complexity) -- EXCEPT (v26, FOLD_PREMIUM_VS_EXTREME_
      AGGRO, untested): facing 2+ raises, if the current to_call is already
      >=50% of hero's remaining stack AND the raiser is a known Nit/TAG,
      fold QQ/AKs/AKo (never AA/KK -- see NEVER_FOLD_PREFLOP).
    - Else, if facing exactly one raise AND the raiser is a known Nit/TAG/
      LAG (high real fold-to-raise, see TIGHT_ARCHETYPES_FOR_DONK_BLUFF)
      AND your hand is in BLUFF_3BET_RANGE (v24, BLUFF_3BET_VS_TIGHT, untested
      -- see the constant's comment above): bluff-raise (3-bet) instead of
      just calling, on the theory that these opponents fold enough for a
      3-bet with no real hand to show a profit.
    - Else, if facing exactly one raise: call with a hand in your position's
      CALL range (half the open VPIP, e.g. UTG ~7% / BTN ~13.3% -- the
      tighter, stronger half of what you'd open) -- (v30, SIZE_SCALED_
      CALL_RANGE, untested) widened by 30% VPIP if the raise-to is <=2bb
      (a cheap price), or narrowed by 30% VPIP if it's >=4bb (a worse
      price, usually a stronger range behind it), instead of one fixed
      range regardless of how big the actual raise was.
    - Else: fold.

  POSTFLOP, checked to (to_call <= 0), any street:
    - Bet ~55% pot if your hand is top-pair-or-better (value bet) --
      regardless of whether you had preflop initiative. Sizing tiers on
      top of that base, each independently untested: (v28, OPTIMAL_VALUE_
      SIZING_PER_ARCHETYPE) a real EV comparison between the standard and
      big sizing for whatever archetype is actually known, using that
      archetype's own real fold rate at each size -- overrides A2's
      Nit/TAG-only shortcut when it fires; (v27, RIVER_OVERBET_NUTS_VS_
      LOOSE) a genuine overbet (150% pot) on the river specifically with
      a near-nut hand (trips+) against a known loose/weak archetype.
    - Flop ONLY, additionally: bet ~55% pot with ANY hand if you had preflop
      initiative and haven't bet yet this street (the one Tier-1 fold-equity
      cbet -- confirmed by A/B test to be worth keeping).
    - Turn/river ONLY, additionally (v25, BARREL_BLUFF_VS_TIGHT, untested):
      bet with no hand at all if you had preflop initiative, haven't bet
      yet this street, a real scare card just arrived (a fresh overcard or
      a new flush possibility -- see _is_scare_card), and the single live
      opponent is a known Nit/TAG/LAG.
    - Otherwise: check. "Don't auto-barrel" means don't fire without a hand
      on the turn/river -- it does not mean never bet a strong hand.

  POSTFLOP, facing a bet, any street:
    - Call with top-pair-or-better (rank-count based -- see
      has_top_pair_or_better -- now including made straights/flushes). v22
      tested raising instead with two-pair-or-better (VALUE_RAISE_FACING_
      BET, has_very_strong_hand) -- measured WORSE (-9.66 bb/100, see the
      constant's comment above), shipped OFF; call-only stays the live
      default even for a flopped set.
    - Else, IF the specific opponent who bet is a known Loose-passive/
      Station/Maniac (see LOOSE_ARCHETYPES): call with ANY pair or better
      (has_any_pair_or_better) instead of the stricter top-pair bar. This is
      the bot's one deliberate piece of opponent modeling -- see the v10 note
      above for why it's worth so much more than everything else combined.
    - Else call with a real flush or open-ended-straight-ish draw IF the
      price is at least as good as the draw's rough continue-equity
      (~35% w/ two cards to come on the flop, ~19% w/ one card on the turn --
      see should_call_with_draw). Never on the river (no card left to come).
    - Else fold.

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

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
sys.path.insert(0, str(ANALYSIS_ROOT))

from src.analysis.hand_rankings import RANKS, compute_hand_rankings
from src.analysis.implied_range import implied_range
from src.pipeline.board_texture import texture_features

from backend.bots.behavior_clone import _seat_position
from backend.engine.hand import Hand

OPEN_VPIP_BY_POSITION = {"UTG": 0.139, "MP": 0.165, "CO": 0.216, "BTN": 0.266, "SB": 0.245}
CALL_VPIP_BY_POSITION = {pos: vpip * 0.5 for pos, vpip in OPEN_VPIP_BY_POSITION.items()}

# v30 (SIZE_SCALED_CALL_RANGE): CALL_VPIP_BY_POSITION implicitly assumes
# every raise is OPEN_SIZING_BB (2.5bb) -- a min-raise to 2bb offers a much
# better price than a raise to 5bb, but the call range doesn't currently
# adjust either way (the fixed hand-strength range is the same regardless
# of the actual pot odds on offer). Real strategy calls wider against a
# smaller raise and narrower against a bigger one (worse price, and
# usually a stronger range behind it too). Three discrete tiers (narrow/
# standard/wide) rather than a continuous per-hand computation, same
# reasoning as every other precomputed range tier in this file (steal_
# ranges, etc.) -- picked by comparing the actual raise-to size (in bb)
# against two thresholds, not a continuous function of size.
SIZE_SCALED_CALL_RANGE = False  # flip True to A/B-test against the baseline (one fixed call range regardless of raise size)
SMALL_RAISE_BB_THRESHOLD = 2.0  # raise-to at or below this many bb -- wider call range
BIG_RAISE_BB_THRESHOLD = 4.0  # raise-to at or above this many bb -- narrower call range
CALL_VPIP_WIDE_MULTIPLIER = 1.3
CALL_VPIP_NARROW_MULTIPLIER = 0.7

# v14, part 1 (STEAL_WIDER_VS_NIT): PokerDom_Microlimits_Analysis's
# archetype_vs_raise.csv shows Nit folds to a preflop raise 90-93% of the
# time at EVERY position (BB 90.3%, BTN 92.7%, CO 93.1%, MP 91.6%, SB 92.7%)
# -- an order of magnitude more foldy than any other archetype. Mirrors the
# existing LOOSE_ARCHETYPES postflop rule, but on the betting side: widen the
# open range when every live opponent still to act is a known Nit.
STEAL_VPIP_BY_POSITION = {pos: min(1.0, vpip + 0.15) for pos, vpip in OPEN_VPIP_BY_POSITION.items()}
TIGHT_ARCHETYPES_FOR_STEAL = {"Nit"}
STEAL_WIDER_VS_NIT = True  # flip False to A/B-test against the baseline (normal open range regardless of opponent)

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

# v14, A2: archetype_facing_bet.csv's "large" bucket shows fold% to a big bet
# scales with how tight the archetype is (Nit 73-75%, TAG 66-72%) but barely
# moves for loose archetypes (Station/Maniac ~52-62%, close to their fold%
# at smaller sizes too) -- a bigger bet buys real extra fold equity against
# Nit/TAG specifically, and just inflates the pot with no extra folds against
# Station/Maniac/Loose-passive. Only applied to hero's OWN value bet (the
# to_call<=0 branch), heads-up only (opponent identity is ambiguous
# multiway) -- sizing up a bluff isn't part of this bot's plan either way.
SIZING_TARGET_ARCHETYPES = {"Nit", "TAG"}
BIG_VALUE_SIZING_POT_FRACTION = 0.75
STANDARD_SIZING_POT_FRACTION = 0.525

# v27: see the RIVER_OVERBET_NUTS_VS_LOOSE comment in choose_abc_action's
# checked-to branch. A genuine overbet (>100% pot) -- BIG_VALUE_SIZING_
# POT_FRACTION's 0.75 never crosses the pot itself.
RIVER_OVERBET_NUTS_VS_LOOSE = False  # flip True to A/B-test against the baseline (flat sizing tiers only)
RIVER_OVERBET_POT_FRACTION = 1.5  # standard-theory "genuine overbet" size, not fit to a measured breakeven point

# v28 (OPTIMAL_VALUE_SIZING_PER_ARCHETYPE): A2 above hardcodes "big sizing
# for Nit/TAG only, standard for everyone else" -- a real finding, but only
# checked for those two archetypes; Maniac/Station/Loose-passive/LAG never
# got the same treatment. Real strategy: compute which of the two sizes
# actually maximizes EV for the SPECIFIC archetype involved, using each
# one's own real fold rate (_facing_bet_stats, archetype_facing_bet.csv --
# same table A2 already reads, now looked up live instead of hand-picked
# from two rows of it). Known real limit, not glossed over: that table
# only has 3 pot-size buckets (small<0.4, medium<0.7, large>=0.7 pot
# fraction) -- it can tell "medium vs large" apart but NOT distinguish
# within "large" (a 75%-pot bet and RIVER_OVERBET_POT_FRACTION's 150%-pot
# bet share the same fold-rate row), so this can only choose between the
# two sizes that already exist (STANDARD/BIG), not calibrate a continuous
# optimum -- see _expected_value_of_bet_size's docstring for the rest of
# the disclosed approximation (a single assumed made-hand equity constant,
# not a real per-hand equity read, which this bot deliberately doesn't
# compute anywhere else either).
OPTIMAL_VALUE_SIZING_PER_ARCHETYPE = False  # flip True to A/B-test against the baseline (SIZING_TARGET_ARCHETYPES' hardcoded Nit/TAG-only rule)
ASSUMED_VALUE_HAND_EQUITY = 0.75  # disclosed, single-number approximation of "how often a should_bet hand is still best when called" -- not a real per-hand equity computation

# monster-pot fix, hero side -- see choose_abc_action's
# HERO_PROGRESSIVE_POT_DAMPING comment. Same shape/rationale as behavior_
# clone.py's PROGRESSIVE_POT_DAMPING, applied to hero's own value-bet sizing.
HERO_PROGRESSIVE_POT_DAMPING = True
HERO_POT_DAMPING_START_BB = 5.0
HERO_POT_DAMPING_FULL_BB = 18.0
HERO_POT_DAMPING_FLOOR_FRAC = 0.05

# v15, B2: archetype_facing_bet.csv shows small-bet fold% drops sharply on
# the TURN specifically vs flop/river, across every archetype (e.g. Nit:
# flop-small fold 39% vs turn-small fold 27%) -- a small turn bet doesn't buy
# the fold equity a same-sized flop/river bet would. Since this bot only ever
# bets the turn for value (no turn bluff in this plan -- UNCONDITIONAL_FLOP_
# CBET is flop-only), there's no reason to undersize there: reuse the same
# BIG_VALUE_SIZING_POT_FRACTION tier on the turn regardless of opponent
# archetype, rather than adding a third sizing number to keep this simple.
SIZE_UP_ON_TURN = True  # flip False to A/B-test against the flat standard-fraction baseline

# v23, two more sizing-by-context theories (2026-08-11, sourced from
# published exploitative-sizing strategy, not read off a real-data table --
# untested hypotheses, standard-theory numbers): value-bet sizing here has
# always been a flat STANDARD_SIZING_POT_FRACTION regardless of (a) how
# strong the made hand actually is, or (b) how draw-heavy the board is --
# explicitly disclosed as a known gap in this file's "Known, disclosed
# simplifications" section ("no polarization"). Exploitative-sizing theory
# says: against opponents who don't adjust to bet size (confirmed true of
# this population's ML bots outside the two narrow hero-adaptation features
# in behavior_clone.py), size UP with genuinely strong hands to extract more,
# and size UP on wet/drawy boards to charge draws properly instead of giving
# a cheap price. Both independently toggleable, same lesson as v15 B1/B2:
# a bundled test can't tell you which part helped.
SIZE_UP_WITH_VERY_STRONG_HAND = False  # bet BIG_VALUE_SIZING_POT_FRACTION instead of standard with two-pair-or-better (has_very_strong_hand)
SIZE_UP_ON_WET_BOARD = False  # bet BIG_VALUE_SIZING_POT_FRACTION instead of standard on a two-tone/monotone/well-connected board

# v16, C1: the bot currently treats "someone already limped" identically to
# "unopened pot" -- always OPEN_SIZING_BB flat. Standard live convention is
# to isolate a limper for MORE than a plain open (open size + ~1bb per
# limper), both to charge the limper for their speculative hand and to price
# out anyone left to act. This is a standard-theory sizing convention, not a
# number fit to a specific measured breakeven point (unlike A2/B2's
# archetype-table-derived sizes) -- flagged as such.
ISO_RAISE_OVER_LIMPERS = True  # flip False to A/B-test against the flat OPEN_SIZING_BB baseline
ISO_SIZING_PER_LIMPER_BB = 1.0

# v29: see the ISO_WIDER_RANGE_OVER_LIMPERS comment at its use site above
# (n_raises==0 branch). Standard live-poker convention (isolate limpers
# wider, not just bigger) -- not fit to a measured breakeven point, same
# disclosure as C1 itself.
ISO_WIDER_RANGE_OVER_LIMPERS = False  # flip True to A/B-test against the baseline (same range as a plain open, regardless of limpers)

# v19: open bigger with a premium hand (reuses VALUE_3BET_TIGHT below as the
# "premium" set), stacking with the C1 per-limper bonus above -- i.e. a
# premium hand opened over 2 limpers gets BOTH bonuses. User's hypothesis,
# untested until now; note this cuts against the usual "keep your whole
# range's sizing the same so it isn't readable" argument, worth checking
# empirically rather than assuming either way given how this file's other
# theory-first guesses (A1/A2/B1/B2) mostly measured as noise.
SIZE_UP_PREMIUM_OPENS = False  # flip False to A/B-test against flat sizing regardless of hand strength
PREMIUM_OPEN_SIZING_BONUS_BB = 1.5

# v17, C2: archetype_facing_bet_by_initiative.csv (new this session --
# PokerDom_Microlimits_Analysis/scripts/build_archetype_tables.py, extended
# to tag each postflop bet with whether the bettor had preflop initiative)
# shows Nit/TAG/LAG fold to a donk bet/lead meaningfully more than to a
# same-sized cbet (Nit +13.6pp, TAG +9.3pp, LAG +6.0pp on large real
# samples, 60k-460k rows per cell); Station/Maniac showed no real
# difference and are deliberately excluded. See the choose_abc_action
# comment for the actual rule.
TIGHT_ARCHETYPES_FOR_DONK_BLUFF = {"Nit", "TAG", "LAG"}
DONK_BLUFF_VS_TIGHT = True  # flip False to A/B-test against the baseline (no donk bluffing at all)

# v25 (BARREL_BLUFF_VS_TIGHT): before this, the bot's only air-bluffing
# mechanisms were a single flop cbet (UNCONDITIONAL_FLOP_CBET, flop-only)
# and a donk-bluff without initiative (v17, DONK_BLUFF_VS_TIGHT) -- there
# was no way to CONTINUE bluffing on the turn or river after a flop cbet,
# even when a genuine scare card (see _is_scare_card -- a fresh overcard,
# or a flush card arriving) makes hero's range look stronger to a tight
# opponent who's already shown they fold to aggression. Published micro-
# stakes strategy (BlackRain79) explicitly recommends this: "bluff nits on
# turn/river when scare cards appear." Reuses TIGHT_ARCHETYPES_FOR_DONK_
# BLUFF -- heads-up only (opponent identity ambiguous multiway, same
# reasoning as every other archetype-gated bluff here), and only continues
# a story hero actually has (had preflop initiative) -- doesn't fire on a
# random checked-to turn/river hero never bet into. Untested, standard-
# theory hypothesis -- see scripts/simulate_abc_bot.py --barrel-bluff.
BARREL_BLUFF_VS_TIGHT = False  # flip True to A/B-test against the baseline (no turn/river scare-card bluff)

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

# v26 (FOLD_PREMIUM_VS_EXTREME_AGGRO): PREMIUM_VS_3BET always continues
# facing 2+ raises, regardless of size or opponent -- even a near-shove
# 4-bet from a known Nit. Real strategy: AA/KK essentially never fold
# preflop (NEVER_FOLD_PREFLOP), but QQ/AKs/AKo are close enough (badly
# dominated by AA/KK, a coinflip at best against a genuinely premium-only
# continuing range) that published exploitative strategy (BlackRain79)
# explicitly recommends folding them to EXTREME aggression from a known
# tight opponent: "fold premium hands to nit aggression." "Extreme" here
# is a simple, standard-theory proxy -- to_call already at least half of
# hero's remaining stack -- not fit to a measured breakeven point. Uses a
# NARROWER archetype set than TIGHT_ARCHETYPES_FOR_DONK_BLUFF (excludes
# LAG): a LAG's 4-bet range is less purely premium than Nit/TAG's, so
# folding QQ to a LAG shove is a materially different, riskier bet than
# folding it to a Nit shove -- untested, not conflated with the donk-bluff
# gate's own archetype set.
FOLD_PREMIUM_VS_EXTREME_AGGRO = False  # flip True to A/B-test against the baseline (always continue with PREMIUM_VS_3BET)
NEVER_FOLD_PREFLOP = {"AA", "KK"}
EXTREME_AGGRO_STACK_FRACTION = 0.5  # to_call >= this fraction of hero's remaining stack counts as "extreme"
TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD = {"Nit", "TAG"}

# v15, B1: archetype_vs_raise.csv / archetype_facing_bet.csv show Maniac and
# Station continue/call facing aggression far more than the population
# average -- a thin value 3-bet (not just a premium hand) is more often still
# ahead of what they'd continue with. Widen VALUE_3BET specifically when the
# original raiser hero is facing is a known Maniac/Station. A modest, round
# widening (not fit to a specific breakeven number) -- the hypothesis is
# "wider works here," not a precise optimal range.
LOOSE_ARCHETYPES_FOR_3BET = {"Maniac", "Station"}
VALUE_3BET_VS_LOOSE = VALUE_3BET | {"99", "88", "AJs", "AJo", "KQs", "KQo"}
WIDER_3BET_VS_LOOSE = True  # flip False to A/B-test against the baseline (VALUE_3BET regardless of raiser)

# v21: a squeeze spot (facing one raise that's ALREADY been called by at
# least one other player before hero acts) has never been treated any
# differently from a heads-up 3-bet spot -- same range, same 3x sizing,
# despite there being extra dead money in the pot and MULTIPLE opponents who
# each have to fold for hero to win it uncontested. Two independent
# hypotheses, each its own flag per this file's own established lesson (v15
# B1/B2 were bundled and had to be re-tested separately) -- untested
# theories, not read off a real-data table (the decision_points.py dataset
# isn't broken out by "raise already called by someone" the way it is by
# archetype/initiative):
#   SQUEEZE_WIDER_RANGE: widen to VALUE_3BET_VS_LOOSE-tier regardless of the
#   raiser's archetype, on the theory that extra dead money justifies a
#   thinner squeeze the same way a loose raiser does in the existing rule.
#   SQUEEZE_SIZE_UP_PER_CALLER: size the squeeze bigger than a flat 3x, one
#   more big blind per caller already in -- mirrors C1's ISO_SIZING_PER_
#   LIMPER_BB pattern (isolating callers, not limpers, but same idea: more
#   dead money in the pot needs a bigger bet to actually fold it all out).
SQUEEZE_WIDER_RANGE = True
SQUEEZE_SIZE_UP_PER_CALLER = False
SQUEEZE_SIZING_PER_CALLER_BB = 1.5

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
# heads-up). v11 bundled all three into one MULTIWAY_AWARE flag, tested the
# bundle, and found it hurt (-7ish bb/100) -- but a bundle can't tell you
# whether all three sub-rules are bad, or one good one is being drowned out
# by two bad ones. Split into three independently-toggleable flags (2026-08-
# 07) to test each in isolation; see the v18 changelog entry for the result.
# MULTIWAY_AWARE stays as a combined read-only flag for any code that wants
# "any multiway awareness is on."
MULTIWAY_NARROW_CALL_RANGE = False  # (1) facing a raise already called by someone else, only continue with VALUE_3BET-tier hands
MULTIWAY_DISABLE_AIR_CBET = False  # (2) the unconditional flop cbet only fires heads-up, made-hand-only otherwise
MULTIWAY_DISABLE_LOOSE_CALL = False  # (3) the any-pair-or-better call vs a known loose archetype only applies heads-up
MULTIWAY_AWARE = MULTIWAY_NARROW_CALL_RANGE or MULTIWAY_DISABLE_AIR_CBET or MULTIWAY_DISABLE_LOOSE_CALL

# v22: the postflop facing-a-bet plan had never raised at all, with ANY hand
# -- "call with top-pair-or-better, else fold" was the entire plan (see the
# "POSTFLOP, facing a bet" rule below). That's a defensible reason not to
# semi-bluff-raise draws (see the BlackRain79 note earlier in this docstring
# -- calling stations have no fold equity to give up), but it never
# distinguished a genuine monster (two pair+/trips/a made straight or flush)
# from a bare top pair: even a flopped set just called. The hypothesis --
# against a population that's 68.5% Loose-passive/Station/Maniac (see
# PokerDom_Practice_App's live_dynamics.py ARCHETYPE_POPULATION_WEIGHTS),
# opponents who structurally don't fold, building a bigger pot with a hand
# that's rarely behind should pay -- TESTED WORSE (scripts/simulate_abc_bot.py
# --value-raise, 80k hands/arm, real rake, ground-truth archetypes, same
# seed): +56.57 bb/100 baseline (CI +/-3.92) vs +46.90 with the raise (CI
# +/-3.68), delta -9.66 bb/100, well outside the combined noise band.
# Working theory for why: this population doesn't just fail to fold, it also
# keeps FIRING -- a call keeps their wide betting/bluffing range live for
# more streets ("let the fish bet for you"), while a raise narrows their
# continuing range to hands that beat two pair often enough to matter AND
# tends to end the hand (fold) or go check-fold from here, cutting off value
# a flat call would have kept extracting. Consistent with this file's other
# "standard theory doesn't transfer to this specific loose/passive-dominated
# population" findings (v11's MULTIWAY_AWARE, the unconditional-flop-cbet
# test) -- shipped OFF, same as those. Gated strictly to two-pair-or-better
# (has_very_strong_hand below, stricter than has_top_pair_or_better) even
# though it's off, so re-testing later starts from a clean value-only rule,
# not a bluff.
VALUE_RAISE_FACING_BET = False  # tested WORSE (-9.66 bb/100, see above) -- kept in code/tests for reference, matches this file's policy for other measured-negative features (MULTIWAY_AWARE etc.)
VALUE_RAISE_MULTIPLIER = 3.0  # standard "raise 3x the bet" sizing, mirrors THREEBET_MULTIPLIER's preflop convention -- only matters if VALUE_RAISE_FACING_BET is flipped on

# 2026-08-11: follow-up to v22's -9.66 bb/100 result -- was that driven by
# the whole two-pair-or-better tier, or specifically by the weaker end of
# it (plain two pair, which loses to a lot of what would call a raise)?
# When True (and VALUE_RAISE_FACING_BET is also True), narrows the trigger
# from has_very_strong_hand to has_trips_or_better -- see that function's
# docstring. Only matters if VALUE_RAISE_FACING_BET is on.
#
# RESULT (scripts/simulate_abc_bot.py --value-raise-tiers, 80k hands/arm,
# real rake, ground-truth archetypes, same seed): confirmed the hypothesis.
# Baseline (call-only) +57.24 bb/100 (CI +/-3.88); raise two-pair-or-better
# (v22) +48.78 (CI +/-3.75, delta -8.46 -- clearly worse, consistent with
# the original v22 finding); raise trips-or-better ONLY +55.46 (CI +/-3.83,
# delta -1.77 -- inside the ~5.4 combined noise band, i.e. NOT a
# demonstrated effect either direction). So: plain two pair was indeed
# driving essentially all of v22's loss -- raising with a genuine near-nut
# hand (trips+) is roughly neutral against this population, not clearly
# harmful. Still shipped False by this file's standing policy of not
# carrying unproven complexity (same call as SIZE_UP_PREMIUM_OPENS above) --
# "not demonstrated harmful" isn't "demonstrated helpful." Real, useful
# takeaway for solve_gto_wizard_like_strategy's multiway raise recommendation
# (live_ev.py) though: it doesn't distinguish hand-strength tiers at all, so
# whatever fraction of its ~39% multiway facing-bet raise recommendations
# come from a plain-two-pair-tier hand is probably still too high, even
# though the tier that includes the nuts looks fine to recommend.
VALUE_RAISE_TRIPS_OR_BETTER_ONLY = False

# v23: see the FOLD_TOP_PAIR_VS_OVERBET comment in choose_abc_action's
# facing-a-bet branch. A/B-test switch: flip True to fold a plain top-pair-
# tier `made` hand (not very_strong -- two pair+ always calls/raises
# regardless of size) when facing a bet bigger than OVERBET_POT_FRACTION of
# the pot. False is the baseline (always call with `made`, this file's
# behavior since v5).
#
# RESULT (scripts/simulate_abc_bot.py --overbet-fold, 30k hands/arm, real
# rake, ground-truth archetypes, same seed): +0.86 bb/100 (58.22 vs 57.35,
# CI +/-6.39 / +/-6.45) -- well inside the ~9.0 combined noise band, NOT a
# demonstrated effect either direction. Made-hand calls being bet-size-
# blind (unlike wizard_like/the CFR solver, which both DO use bet size --
# see live_ev.py) turned out not to be costing this bot anything measurable
# against this population at the one threshold tested (pot-sized bet).
# Shipped False, same standing policy as this file's other unproven flags.
FOLD_TOP_PAIR_VS_OVERBET = False
OVERBET_POT_FRACTION = 1.0  # standard-theory "a bet bigger than the pot" threshold, not fit to a measured breakeven point

# v24: see the BLUFF_3BET_VS_TIGHT comment in choose_abc_action's
# facing-a-raise branch. Sourced from published exploitative micro-stakes
# strategy (BlackRain79), not read off a real-data table -- a standard-
# theory hand set (blocker-heavy suited aces + suited connectors/one-
# gappers + a couple offsuit broadways), disjoint from VALUE_3BET_WIDE, not
# fit to a specific measured breakeven point.
#
# MOTIVATION, real data: PokerDom_Microlimits_Analysis/scripts/characterize_
# winning_players.py correlated real per-player stats against real bb_per_100
# across 686 players with >=5000 hands -- 3bet% was the SECOND-strongest
# predictor of winning (rho=+0.4678, almost as strong as PFR's +0.4749),
# and real winners' top decile 3-bets more than double the rate of the
# bottom decile (5.4% vs 2.4%) against a population Tier 2's own finding
# says barely 3-bets at all. That's a real, large, population-level signal
# that more 3-betting associates with winning.
#
# RESULT, this specific implementation: does NOT clear the bar, despite the
# population correlation above. scripts/simulate_abc_bot.py --bluff-3bet,
# real rake, ground-truth archetypes, same seed:
#   80k hands/arm:  baseline +57.90 (CI +/-3.92) vs v24 +62.19 (CI +/-3.96),
#                   delta +4.29 -- leaning positive, inside the ~5.6 combined
#                   noise band.
#   300k hands/arm: baseline +57.12 (CI +/-2.03) vs v24 +59.67 (CI +/-2.04),
#                   delta +2.56 -- STILL inside the ~2.9 combined noise band
#                   (barely), same pattern SQUEEZE_WIDER_RANGE's own 80k->
#                   300k retest showed (an 80k lean that shrinks toward the
#                   noise floor at real power, not a suppressed real effect).
# Interpretation: the real-data correlation is almost certainly genuine, but
# most likely reflects that players who 3-bet more ALSO tend to be better
# overall (postflop play, hand reading, etc.), not that bolting this one
# narrow bluff-3-bet rule onto an otherwise-unchanged bot captures that same
# edge. Shipped False, same standing policy as this file's other unproven
# flags -- "a real correlation exists in the population" and "this specific
# rule is a demonstrated fix" are different claims, and only the first one
# is established here.
BLUFF_3BET_VS_TIGHT = False  # flip True to A/B-test against the baseline (call-or-fold with these hands, no bluff 3-bet)
BLUFF_3BET_RANGE = {"A9o", "A8o", "A5s", "A4s", "KQo", "KJs", "QJs", "JTs", "T9s", "98s"}

_rankings_cache = None
_open_range_cache: dict[str, set] = {}
_call_range_cache: dict[str, set] = {}
_steal_range_cache: dict[str, set] = {}
_call_range_wide_cache: dict[str, set] = {}
_call_range_narrow_cache: dict[str, set] = {}


def _ranges():
    global _rankings_cache, _open_range_cache, _call_range_cache, _steal_range_cache
    global _call_range_wide_cache, _call_range_narrow_cache
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
        _steal_range_cache = {
            pos: set(implied_range(vpip, _rankings_cache)) | REAL_DATA_RANGE_ADDITIONS.get(pos, set())
            for pos, vpip in STEAL_VPIP_BY_POSITION.items()
        }
        # v30 (SIZE_SCALED_CALL_RANGE): two more tiers around the existing
        # call range, +/- CALL_VPIP_WIDE_MULTIPLIER/CALL_VPIP_NARROW_
        # MULTIPLIER, so the call range can scale with how big the actual
        # raise is (see the constant's comment below) -- same technique as
        # steal_ranges, a precomputed alternate tier rather than a fresh
        # per-decision computation.
        _call_range_wide_cache = {
            pos: set(implied_range(vpip * CALL_VPIP_WIDE_MULTIPLIER, _rankings_cache)) | REAL_DATA_CALL_RANGE_ADDITIONS.get(pos, set())
            for pos, vpip in CALL_VPIP_BY_POSITION.items()
        }
        _call_range_narrow_cache = {
            pos: set(implied_range(vpip * CALL_VPIP_NARROW_MULTIPLIER, _rankings_cache))
            for pos, vpip in CALL_VPIP_BY_POSITION.items()
        }
    return (
        _open_range_cache,
        _call_range_cache,
        _steal_range_cache,
        _call_range_wide_cache,
        _call_range_narrow_cache,
    )


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


def _last_preflop_raiser_seat(hand: Hand) -> int | None:
    preflop_raises = [a for a in hand.actions if a.street == "preflop" and a.action == "raises"]
    return preflop_raises[-1].seat if preflop_raises else None


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


def _n_limpers_preflop(hand: Hand) -> int:
    """Callers before any raise this preflop -- i.e. limps into what's still
    an technically-unopened pot from hero's perspective (n_raises==0 branch).
    See ISO_RAISE_OVER_LIMPERS above."""
    count = 0
    for a in hand.actions:
        if a.street != "preflop":
            continue
        if a.action == "raises":
            break
        if a.action == "calls":
            count += 1
    return count


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


def has_very_strong_hand(hole: list[str], board: list[str]) -> bool:
    """Strictly stronger than has_top_pair_or_better -- excludes plain top
    pair and a plain overpair (still call-only), keeps two-pair-or-better,
    trips+, and made straights/flushes. Gates VALUE_RAISE_FACING_BET (see
    above): a hand this strong is rarely behind, so raising to build the pot
    against a population that mostly doesn't fold is a value play, not a
    bluff -- deliberately NOT extended to plain top pair, which is strong
    enough to call profitably but not strong enough to want a bigger pot
    against an unknown range."""
    if not board:
        return False
    if _has_made_flush(hole, board) or _has_made_straight(hole, board):
        return True
    counts = _rank_counts(hole + board)
    pair_ranks = [r for r, n in counts.items() if n >= 2]
    if len(pair_ranks) >= 2:
        return True  # two pair or better
    return bool(pair_ranks) and counts[pair_ranks[0]] >= 3  # trips+


def has_trips_or_better(hole: list[str], board: list[str]) -> bool:
    """A narrower tier than has_very_strong_hand: EXCLUDES plain two pair,
    keeps trips, full houses, quads, and made straights/flushes. Added to
    test whether v22's -9.66 bb/100 result (VALUE_RAISE_FACING_BET raising
    with two-pair-or-better) was driven specifically by the weaker end of
    that tier -- plain two pair is a real hand but still loses to a lot of
    what calls a raise (trips, straights, better two pairs), unlike this
    narrower near-nut tier. See VALUE_RAISE_TRIPS_OR_BETTER_ONLY."""
    if not board:
        return False
    if _has_made_flush(hole, board) or _has_made_straight(hole, board):
        return True
    counts = _rank_counts(hole + board)
    pair_ranks = [r for r, n in counts.items() if n >= 2]
    return any(counts[r] >= 3 for r in pair_ranks)  # trips, full house, or quads -- never plain two pair


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


def _live_opponent_seats(hand: Hand, seat: int) -> list[int]:
    return [s for s, p in hand.players.items() if s != seat and p.in_hand]


def _all_live_opponents_are_tight(hand: Hand, seat: int, opponent_archetypes: dict[int, str] | None) -> bool:
    """True only if every opponent still live to act this hand is a KNOWN
    tight archetype (see TIGHT_ARCHETYPES_FOR_STEAL / STEAL_WIDER_VS_NIT) --
    unknown/missing archetypes don't count as tight, so this only fires with
    real information, never as a default."""
    if not opponent_archetypes:
        return False
    live = _live_opponent_seats(hand, seat)
    if not live:
        return False
    return all(opponent_archetypes.get(s) in TIGHT_ARCHETYPES_FOR_STEAL for s in live)


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


def _is_wet_board(board: list[str]) -> bool:
    """Reuses the ML bots' own board_texture.py feature extraction (same
    module behavior_clone.py already relies on) rather than redefining
    "wet" a second way. "Wet" = a real flush possibility (two_tone or
    monotone) or a well-connected straight-drawy board (connectedness>=2,
    i.e. at least two small rank-gaps among the board cards) -- gates
    SIZE_UP_ON_WET_BOARD above."""
    if len(board) < 3:
        return False
    t = texture_features(board)
    return bool(t["board_two_tone"] or t["board_monotone"] or t["board_connectedness"] >= 2)


def _is_scare_card(hand: Hand) -> bool:
    """A "scare card" arrived on THIS street (turn or river): either the
    new card outranks every card that was already on the board (a fresh
    overcard -- e.g. an Ace turning after a low flop), or it just made the
    board two-tone/monotone (a flush card arriving) when it wasn't before.
    A simple, disclosed heuristic -- doesn't try to detect e.g. a card that
    completes a gutshot or pairs a scary rank the way a full range-vs-range
    read would; gates BARREL_BLUFF_VS_TIGHT below."""
    board = hand.board
    if hand.street not in ("turn", "river") or len(board) < 4:
        return False
    board_before, new_card = board[:-1], board[-1]
    if _RANK_ORDER.index(new_card[0]) > max(_RANK_ORDER.index(c[0]) for c in board_before):
        return True
    return _is_wet_board(board) and not _is_wet_board(board_before)


_facing_bet_table_cache: pd.DataFrame | None = None


def _facing_bet_fold_pct(street: str, pot_fraction: float, archetype: str) -> float | None:
    """Independent copy of backend/ev/live_ev.py's opponent_facing_bet_stats
    -- can't import that module directly (live_ev.py imports choose_abc_
    action from THIS module, so the reverse import would be circular).
    Same bucket logic (small<0.4, medium<0.7, large>=0.7 pot fraction),
    same source table (PokerDom_Microlimits_Analysis/data/reference/
    archetype_facing_bet.csv, already what A2/SIZING_TARGET_ARCHETYPES was
    hand-read from). Returns None (not a default) when there's no row for
    this exact (archetype, street, bucket) -- callers should fall back to
    the existing hardcoded behavior rather than guess a population number,
    since that's a different question (a specific archetype's real
    tendency) than this file has ever tried to answer with a blend."""
    global _facing_bet_table_cache
    if _facing_bet_table_cache is None:
        _facing_bet_table_cache = pd.read_csv(ANALYSIS_ROOT / "data" / "reference" / "archetype_facing_bet.csv")
    bucket = "small" if pot_fraction < 0.4 else ("medium" if pot_fraction < 0.7 else "large")
    row = _facing_bet_table_cache[
        (_facing_bet_table_cache.archetype == archetype)
        & (_facing_bet_table_cache.street == street)
        & (_facing_bet_table_cache.pot_bucket == bucket)
    ]
    if row.empty:
        return None
    return float(row.iloc[0]["fold_pct"])


def _optimal_value_sizing(hand: Hand, archetype: str) -> float | None:
    """v28: which of the two existing value-bet sizes (STANDARD_SIZING_
    POT_FRACTION / BIG_VALUE_SIZING_POT_FRACTION) actually maximizes EV
    against THIS specific archetype, using its real fold rate at each size
    (see _facing_bet_fold_pct) -- rather than A2's hardcoded "big sizing
    for Nit/TAG only" rule, which never checked the other four archetypes.

    EV(size) ~= fold_pct(size) * pot_before + (1 - fold_pct(size)) *
    (ASSUMED_VALUE_HAND_EQUITY * (pot_before + bet_size) - bet_size),
    the standard "bet EV vs a range that either folds or calls" formula
    (same shape as gto_wizard_like.py's raise EV fix) with ONE disclosed
    approximation this bot doesn't try to avoid: a single assumed equity
    number for "how often hero's hand is still best when called," not a
    real per-hand equity read (this bot has no numeric equity computation
    anywhere else either -- that's what backend/ev/live_ev.py's solvers
    are for, not this hand-coded strategy). Returns None if there's no
    real data for this archetype at either size, so the caller can fall
    back to the existing hardcoded default instead of guessing."""
    pot_before = sum(p.total_contributed for p in hand.players.values())
    if pot_before <= 0:
        return None
    fold_medium = _facing_bet_fold_pct(hand.street, STANDARD_SIZING_POT_FRACTION, archetype)
    fold_large = _facing_bet_fold_pct(hand.street, BIG_VALUE_SIZING_POT_FRACTION, archetype)
    if fold_medium is None or fold_large is None:
        return None

    def _ev(fold_pct: float, fraction: float) -> float:
        bet_size = pot_before * fraction
        ev_if_called = ASSUMED_VALUE_HAND_EQUITY * (pot_before + bet_size) - bet_size
        return fold_pct * pot_before + (1 - fold_pct) * ev_if_called

    ev_medium = _ev(fold_medium, STANDARD_SIZING_POT_FRACTION)
    ev_large = _ev(fold_large, BIG_VALUE_SIZING_POT_FRACTION)
    return BIG_VALUE_SIZING_POT_FRACTION if ev_large >= ev_medium else STANDARD_SIZING_POT_FRACTION


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
    open_ranges, call_ranges, steal_ranges, call_ranges_wide, call_ranges_narrow = _ranges()
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
            # v14, part 1 (STEAL_WIDER_VS_NIT): widen the open range when
            # every live opponent is a known Nit (90-93% fold to a raise at
            # every position -- see the constant's comment above).
            use_steal = STEAL_WIDER_VS_NIT and _all_live_opponents_are_tight(hand, seat, opponent_archetypes)
            # v29 (ISO_WIDER_RANGE_OVER_LIMPERS): C1 (ISO_RAISE_OVER_LIMPERS)
            # already isolates limpers for MORE money but with the SAME
            # range as a plain open -- real strategy also isolates them
            # with a WIDER range, since a limper has already shown a weak/
            # speculative hand and doesn't represent the fold equity a
            # normal opener behind them would need to respect. Reuses
            # steal_ranges (the same "+15pp VPIP" widened range
            # STEAL_WIDER_VS_NIT already computes) rather than a third
            # precomputed range tier -- conceptually the same move (widen
            # against a shown weakness), just a different trigger. If
            # BOTH conditions apply, either one is enough to widen.
            use_iso_wide = ISO_WIDER_RANGE_OVER_LIMPERS and _n_limpers_preflop(hand) >= 1
            open_range = steal_ranges.get(position) if (use_steal or use_iso_wide) else open_ranges.get(position)
            if open_range and notation in open_range:
                # v16, C1 (see ISO_RAISE_OVER_LIMPERS above): size up over
                # already-limped-in callers instead of the flat open size.
                sizing_bb = OPEN_SIZING_BB
                if ISO_RAISE_OVER_LIMPERS:
                    sizing_bb += ISO_SIZING_PER_LIMPER_BB * _n_limpers_preflop(hand)
                # v19, hand-strength-dependent sizing: size up further with a
                # premium hand (reuses VALUE_3BET_TIGHT as the "premium" set,
                # rather than defining a second premium-hand list) -- untested
                # theory, not read off any archetype table, opposite of the
                # usual balanced-range argument for keeping opens flat. Testing
                # it rather than assuming either direction.
                if SIZE_UP_PREMIUM_OPENS and notation in VALUE_3BET_TIGHT:
                    sizing_bb += PREMIUM_OPEN_SIZING_BONUS_BB
                amount = hand.big_blind * sizing_bb
                amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
                return ("raise", amount)
            return ("fold" if to_call > 0 else "check", None)

        if n_raises >= 2:
            if notation in PREMIUM_VS_3BET:
                # v26 (see FOLD_PREMIUM_VS_EXTREME_AGGRO above): even a
                # premium hand can fold to an extreme-sized re-raise from a
                # known tight opponent -- AA/KK are the one exception that
                # never folds regardless.
                if (
                    FOLD_PREMIUM_VS_EXTREME_AGGRO
                    and notation not in NEVER_FOLD_PREFLOP
                    and opponent_archetypes
                    and player.stack > 0
                    and to_call >= EXTREME_AGGRO_STACK_FRACTION * player.stack
                ):
                    raiser_seat = _last_preflop_raiser_seat(hand)
                    raiser_archetype = opponent_archetypes.get(raiser_seat) if raiser_seat is not None else None
                    if raiser_archetype in TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD:
                        return ("fold", None)
                return ("call", None)
            return ("fold", None)

        # Facing exactly one raise.
        n_callers_in = _n_callers_since_last_raise_preflop(hand)
        # v15, B1: widen the value-3-bet range when the raiser hero is facing
        # is a known Maniac/Station (see LOOSE_ARCHETYPES_FOR_3BET above).
        value_3bet_range = VALUE_3BET
        if WIDER_3BET_VS_LOOSE and opponent_archetypes:
            raiser_seat = _last_preflop_raiser_seat(hand)
            if raiser_seat is not None and opponent_archetypes.get(raiser_seat) in LOOSE_ARCHETYPES_FOR_3BET:
                value_3bet_range = VALUE_3BET_VS_LOOSE
        # v21 (SQUEEZE_WIDER_RANGE): see the constant's comment above -- dead
        # money from the caller(s) already in justifies the same widening a
        # loose raiser does, so just take the wider of the two ranges.
        if SQUEEZE_WIDER_RANGE and n_callers_in > 0:
            value_3bet_range = VALUE_3BET_VS_LOOSE
        if notation in value_3bet_range:
            amount = hand.current_bet * THREEBET_MULTIPLIER
            # v21 (SQUEEZE_SIZE_UP_PER_CALLER): size the squeeze bigger than a
            # flat 3x to actually price out the extra caller(s) -- see the
            # constant's comment above.
            if SQUEEZE_SIZE_UP_PER_CALLER:
                amount += hand.big_blind * SQUEEZE_SIZING_PER_CALLER_BB * n_callers_in
            amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
            return ("raise", amount)
        # v24 (BLUFF_3BET_VS_TIGHT): this bot has never had a bluff 3-bet --
        # VALUE_3BET(_WIDE) is the only 3-betting range that exists, so every
        # non-premium hand just calls or folds facing a raise. Published
        # exploitative micro-stakes strategy (BlackRain79's "How to Beat
        # Micro Stakes Poker") explicitly recommends 3-betting speculative
        # hands (their examples: A9o, JTo-type) against a specific regular
        # with an 80%+ fold-to-3-bet rate -- and archetype_vs_raise.csv
        # (PokerDom_Microlimits_Analysis) shows Nit folds to a raise 90-93%
        # and TAG 82-90% at every position with a real sample except UTG,
        # both clearing that bar -- reuses TIGHT_ARCHETYPES_FOR_DONK_BLUFF
        # (Nit/TAG/LAG) rather than defining a second similar-but-different
        # tight-archetype set. Checked before the call range below: 3-betting
        # here is specifically +EV BECAUSE these opponents fold so much, not
        # because the hand is strong enough to profitably call with, so it
        # should win over just calling when both would otherwise apply.
        if BLUFF_3BET_VS_TIGHT and opponent_archetypes:
            raiser_seat = _last_preflop_raiser_seat(hand)
            raiser_archetype = opponent_archetypes.get(raiser_seat) if raiser_seat is not None else None
            if raiser_archetype in TIGHT_ARCHETYPES_FOR_DONK_BLUFF and notation in BLUFF_3BET_RANGE:
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
        already_multiway = MULTIWAY_NARROW_CALL_RANGE and _n_callers_since_last_raise_preflop(hand) > 0
        if ALLOW_CALLING_RAISES and not already_multiway:
            # v30 (see SIZE_SCALED_CALL_RANGE above): scale which call-range
            # tier applies by the ACTUAL raise-to size instead of always
            # using the one fixed range. hand.current_bet is the raise-to
            # amount at this point (facing exactly one raise).
            call_range = call_ranges.get(position)
            if SIZE_SCALED_CALL_RANGE:
                raise_bb = hand.current_bet / hand.big_blind if hand.big_blind else 0.0
                if raise_bb <= SMALL_RAISE_BB_THRESHOLD:
                    call_range = call_ranges_wide.get(position)
                elif raise_bb >= BIG_RAISE_BB_THRESHOLD:
                    call_range = call_ranges_narrow.get(position)
            if call_range and notation in call_range:
                return ("call", None)
        return ("fold", None)

    # postflop
    had_initiative = _had_preflop_initiative(hand, seat)
    n_bets = _n_bets_or_raises_this_street(hand)
    made = has_top_pair_or_better(player.hole_cards, hand.board)
    if VALUE_RAISE_TRIPS_OR_BETTER_ONLY:
        very_strong = has_trips_or_better(player.hole_cards, hand.board)
    else:
        very_strong = has_very_strong_hand(player.hole_cards, hand.board)
    pot_before = sum(p.total_contributed for p in hand.players.values())
    n_live_opps_2plus = _n_live_opponents(hand, seat) >= 2
    is_multiway = MULTIWAY_AWARE and n_live_opps_2plus  # combined flag; specific sub-rules below use their own flag

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
        if MULTIWAY_DISABLE_AIR_CBET and n_live_opps_2plus:
            cbet_with_air = False
        # v17, C2 (see TIGHT_ARCHETYPES_FOR_DONK_BLUFF above): a donk bet with
        # NO hand at all, specifically into a known Nit/TAG/LAG -- these
        # archetypes fold to a donk/lead meaningfully more than to a same-
        # sized cbet (archetype_facing_bet_by_initiative.csv: Nit +13.6pp,
        # TAG +9.3pp, LAG +6.0pp; Station/Maniac showed no real difference,
        # correctly excluded). This is a genuinely new behavior, not a
        # sizing/range tweak on an existing bet -- the bot previously only
        # ever bluffed as an in-position flop cbet with initiative.
        donk_bluff_with_air = False
        if DONK_BLUFF_VS_TIGHT and not had_initiative and n_bets == 0 and opponent_archetypes:
            # heads-up-only is already enforced below via len(...)==1 --
            # deliberately not gated by is_multiway/MULTIWAY_AWARE, so this
            # v17 rule stays independent of the (2026-08-07-split) v18
            # multiway sub-rule flags being tested.
            donk_live_opponents = _live_opponent_seats(hand, seat)
            if len(donk_live_opponents) == 1:
                if opponent_archetypes.get(donk_live_opponents[0]) in TIGHT_ARCHETYPES_FOR_DONK_BLUFF:
                    donk_bluff_with_air = True
        # v25 (see BARREL_BLUFF_VS_TIGHT above): continue bluffing a scare
        # card on the turn/river against a known tight opponent, if hero
        # had preflop initiative (a real story to tell) and got checked to
        # again with no hand. Heads-up only, same reasoning as the donk
        # bluff above.
        barrel_bluff_with_air = False
        if (
            BARREL_BLUFF_VS_TIGHT
            and had_initiative
            and n_bets == 0
            and hand.street in ("turn", "river")
            and opponent_archetypes
            and _is_scare_card(hand)
        ):
            barrel_live_opponents = _live_opponent_seats(hand, seat)
            if len(barrel_live_opponents) == 1:
                if opponent_archetypes.get(barrel_live_opponents[0]) in TIGHT_ARCHETYPES_FOR_DONK_BLUFF:
                    barrel_bluff_with_air = True
        should_bet = made or cbet_with_air or donk_bluff_with_air or barrel_bluff_with_air
        if should_bet and n_bets == 0:
            # v14, A2 (see SIZING_TARGET_ARCHETYPES above): size up specifically
            # against a known Nit/TAG, where a bigger bet measurably buys extra
            # folds -- against everyone else (unknown, or a known loose
            # archetype that calls regardless of size), keep the standard
            # sizing. Heads-up only, same reasoning as LOOSE_ARCHETYPES below:
            # opponent identity is ambiguous once 2+ live opponents are facing
            # the same bet.
            sizing = STANDARD_SIZING_POT_FRACTION
            live_opponents = _live_opponent_seats(hand, seat)
            if opponent_archetypes and len(live_opponents) == 1:
                if opponent_archetypes.get(live_opponents[0]) in SIZING_TARGET_ARCHETYPES:
                    sizing = BIG_VALUE_SIZING_POT_FRACTION
            # v28 (see OPTIMAL_VALUE_SIZING_PER_ARCHETYPE above): overrides
            # A2's hardcoded Nit/TAG-only choice with a real EV comparison
            # for WHATEVER archetype is actually known, using that
            # archetype's own real fold rate at each size -- falls back to
            # A2's choice (leaves `sizing` unchanged) when there's no real
            # data for this exact archetype/street/bucket combination.
            if OPTIMAL_VALUE_SIZING_PER_ARCHETYPE and opponent_archetypes and len(live_opponents) == 1:
                archetype = opponent_archetypes.get(live_opponents[0])
                if archetype:
                    optimal = _optimal_value_sizing(hand, archetype)
                    if optimal is not None:
                        sizing = optimal
            # v15, B2 (see SIZE_UP_ON_TURN above): small turn bets don't buy
            # extra folds here regardless of opponent -- size up unconditionally.
            if SIZE_UP_ON_TURN and hand.street == "turn":
                sizing = BIG_VALUE_SIZING_POT_FRACTION
            # v23 (see SIZE_UP_WITH_VERY_STRONG_HAND/SIZE_UP_ON_WET_BOARD
            # above): two more untested sizing-by-context theories, each its
            # own flag. `made` here can also be air-cbet/donk-bluff-triggered
            # (should_bet's other two terms) -- both new rules are correctly
            # no-ops in that case since a bluff has no real hand strength to
            # size up with, and a wet board arguably wants a SMALLER bluff
            # size instead, a separate untested question not conflated here.
            if SIZE_UP_WITH_VERY_STRONG_HAND and made and very_strong:
                sizing = BIG_VALUE_SIZING_POT_FRACTION
            if SIZE_UP_ON_WET_BOARD and made and _is_wet_board(hand.board):
                sizing = BIG_VALUE_SIZING_POT_FRACTION
            # v27 (RIVER_OVERBET_NUTS_VS_LOOSE): a genuine overbet (>100%
            # pot), not just BIG_VALUE_SIZING_POT_FRACTION's 75%, on the
            # river specifically with a real near-nut hand (has_trips_or_
            # better -- the stronger bar, since v22 found plain two pair
            # specifically was the problem tier for extra aggression)
            # against a known loose/weak archetype who's shown they pay off
            # big bets. Published micro-stakes strategy (BlackRain79): "a
            # massive overbet strategy with the nuts on river action cards"
            # is one of the biggest keys to beating micro stakes. Heads-up
            # only, same opponent-identity-ambiguity reasoning as
            # SIZING_TARGET_ARCHETYPES above. Known, disclosed interaction:
            # HERO_PROGRESSIVE_POT_DAMPING below still applies uniformly to
            # whatever `sizing` ends up as, so a genuine overbet in an
            # already-large pot (exactly where overbetting the river with
            # the nuts matters most) may get partially neutered by the
            # monster-pot fix -- not special-cased around, since that fix's
            # whole point was capping runaway sizing regardless of the
            # reason, and the A/B result below measures the NET effect
            # either way.
            if (
                RIVER_OVERBET_NUTS_VS_LOOSE
                and made
                and has_trips_or_better(player.hole_cards, hand.board)
                and hand.street == "river"
                and opponent_archetypes
                and len(live_opponents) == 1
                and opponent_archetypes.get(live_opponents[0]) in LOOSE_ARCHETYPES
            ):
                sizing = RIVER_OVERBET_POT_FRACTION
            # monster-pot fix, hero side (2026-08-07): the earlier fix only
            # touched the ML bots' sizing (backend/bots/behavior_clone.py) --
            # confirmed via a fresh hand-log pull that hero's OWN sizing here
            # is an equally real contributor (a real example: hero betting
            # $44 into an already-~$85 pot on the river, completely
            # undamped). Same progressive-damping shape as the ML-bot fix,
            # applied to hero's value-bet sizing too.
            if HERO_PROGRESSIVE_POT_DAMPING:
                pot_bb_hero = pot_before / hand.big_blind
                if pot_bb_hero > HERO_POT_DAMPING_START_BB:
                    hero_damp = min(1.0, (pot_bb_hero - HERO_POT_DAMPING_START_BB) / (HERO_POT_DAMPING_FULL_BB - HERO_POT_DAMPING_START_BB))
                    sizing = sizing * (1 - hero_damp) + HERO_POT_DAMPING_FLOOR_FRAC * hero_damp
            amount = pot_before * sizing
            amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
            return ("bet", amount)
        return ("check", None)

    # v22 (VALUE_RAISE_FACING_BET, see the constant's comment above): a
    # genuine monster (two pair+) raises for value instead of just calling --
    # checked before the plain `made` call below since very_strong is a
    # strict subset of it. Same progressive pot-damping shape as hero's own
    # value-bet sizing (HERO_PROGRESSIVE_POT_DAMPING), applied to the raise
    # multiplier instead of a bet fraction, so this doesn't reopen the
    # monster-pot problem that fix specifically targeted.
    if VALUE_RAISE_FACING_BET and very_strong:
        multiplier = VALUE_RAISE_MULTIPLIER
        if HERO_PROGRESSIVE_POT_DAMPING:
            pot_bb_hero = pot_before / hand.big_blind
            if pot_bb_hero > HERO_POT_DAMPING_START_BB:
                hero_damp = min(1.0, (pot_bb_hero - HERO_POT_DAMPING_START_BB) / (HERO_POT_DAMPING_FULL_BB - HERO_POT_DAMPING_START_BB))
                multiplier = multiplier * (1 - hero_damp) + 1.0 * hero_damp
        amount = hand.current_bet * multiplier
        amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
        return ("raise", amount)

    # v23 (FOLD_TOP_PAIR_VS_OVERBET): `made` accepts ANY bet size, including
    # a bet bigger than the pot itself -- unlike should_call_with_draw below,
    # which already gates on pot odds. Real strategy folds a marginal top
    # pair to a genuine overbet; a real monster (very_strong, i.e. two
    # pair+) still calls (or raises, if VALUE_RAISE_FACING_BET is on)
    # regardless of size -- only the weaker, non-very_strong portion of
    # `made` (plain top pair / overpair) is gated here. Untested theory, not
    # read off a real-data table (check_bet_size_reveals_strength.py found a
    # real but modest bet-size/hand-strength correlation, not precise enough
    # to derive a specific threshold from) -- testing a standard-theory
    # number (pot-sized bet) rather than assuming either way.
    if made:
        if (
            FOLD_TOP_PAIR_VS_OVERBET
            and not very_strong
            and pot_before > 0
            and (to_call / pot_before) > OVERBET_POT_FRACTION
        ):
            # Falls straight to fold -- deliberately bypasses the
            # loose-archetype any-pair-or-better call below too, so this
            # A/B test isolates one thing (does a plain top pair fold to an
            # overbet) instead of being silently reclaimed by that other
            # rule for loose bettors specifically.
            return ("fold", None)
        return ("call", None)

    if opponent_archetypes and not (MULTIWAY_DISABLE_LOOSE_CALL and n_live_opps_2plus):
        aggressor = _last_aggressor_this_street(hand)
        aggressor_archetype = opponent_archetypes.get(aggressor) if aggressor is not None else None
        if aggressor_archetype in LOOSE_ARCHETYPES and has_any_pair_or_better(player.hole_cards, hand.board):
            return ("call", None)

    if should_call_with_draw(player.hole_cards, hand.board, hand.street, to_call, pot_before):
        return ("call", None)
    return ("fold", None)
