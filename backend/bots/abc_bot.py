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
  demonstrated effect at the time. Shipped False, per this file's standing
  policy of not carrying unproven complexity (same call made for behavior_
  clone.py's reverted 4th monster-pot refinement the same day).

  r20 (2026-08-13): re-tested with the chance-enumeration probe instead of
  the old whole-game method -- the whole-game test above was simply too
  imprecise to see this, not evidence of no effect. Result: +4.00+/-1.89
  bb/100 @ seed42, +3.05+/-1.44 bb/100 @ seed777 (combined-CI-in-quadrature
  2.38 vs a 0.95 delta between them -- well inside, confirmed). Shipped
  True.

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

  2026-08-12 full-model ablation update: the newer chance-enumeration probe
  compared today's full strategy against "full minus one rule" rather than
  testing historical add-one deltas. That supersedes some old keep-on-faith
  defaults: SIZE_UP_ON_TURN was tiny/noisy (+0.46 +/-0.59 when removed),
  ISO_RAISE_OVER_LIMPERS was tiny/noisy (-0.60 +/-0.99 when removed), and
  HERO_PROGRESSIVE_POT_DAMPING looked actively harmful (+72.06 +/-6.94 when
  removed). Those three now ship False. DONK_BLUFF_VS_TIGHT stayed good
  (-11.90 +/-4.22 when removed), and opponent-aware loose calls stayed very
  large (-77.94 +/-10.75 when removed).

  v31 candidate (2026-08-12): user pointed out that the disabled C1
  ISO_RAISE_OVER_LIMPERS did NOT test the more anti-multiway live-poker
  idea: don't isolate limpers with the same/wider range and a small sizing
  bump; instead isolate tighter, with a larger size, to make overcalls less
  attractive and more often get heads-up against the limper. Added
  TIGHT_BIG_ISO_RAISE_LIMPERS as a test flag: 70% of the normal open VPIP,
  4.5bb + 1bb/limper. This is a new theory, not covered by the old r09
  result. Partial adaptive current check was stopped manually once the signal
  was clear: +11.61 +/-3.97 bb/100 at 22k hands, 1311 divergent. Shipped
  True. Follow-up parameter grid found wider+bigger was best: 85% of normal
  open VPIP, 5.5bb + 1.5bb/limper, +22.54 +/-4.77 bb/100 vs the first r12
  default at 10k hands / 490 divergent.

  pf1-pf10 (2026-08-14, built, NOT tested): the ten postflop gaps from
  CLAUDE.md's 2026-08-13 research pass, implemented as off-by-default flags
  the same way r22-r29 were for preflop -- board-texture-dependent c-bet
  sizing (TEXTURE_DEPENDENT_CBET_SIZING), semi-bluff raising draws
  (SEMI_BLUFF_RAISE_DRAWS), range/nut-advantage sizing
  (NUT_ADVANTAGE_SIZING), turn probe betting after a checked flop
  (PROBE_BET_TURN_AFTER_CHECK), delayed c-bet (DELAYED_CBET_MARGINAL, shares
  its check-check detection with the probe bet via
  `_street_was_checked_through`), pot control / checking back marginal made
  hands (POT_CONTROL_MARGINAL_HANDS), SPR-scaled calling thresholds
  (SPR_SCALED_THRESHOLDS), a small river block-bet tier (BLOCK_BET_RIVER),
  blocker-aware river bluff selection (BLOCKER_BASED_RIVER_BLUFF, narrows
  BARREL_BLUFF_VS_TIGHT rather than firing independently). pf2 (multiway
  c-bet reduction) needed no new code -- it already existed as the untested
  MULTIWAY_DISABLE_AIR_CBET flag. All ten default False; existing 191 tests
  pass unchanged; a manual smoke test (each flag flipped True individually,
  then all nine together, 400-600 hands each through scripts/
  simulate_abc_bot.py's real Table/dossier/ML-bot simulation loop) threw no
  exceptions. **None of these have been statistically tested via
  scripts/probe_chance_enumeration.py -- treat every one as a raw,
  unconfirmed hypothesis, same status as r22-r29. Do not run the A/B
  validation without separate explicit go-ahead.**

  pf1-pf10 validation (2026-08-14, same day, user gave explicit go-ahead to
  test): all nine wired presets (pf2 excluded, see above) run adaptive
  chance-enumeration, --comparison current, both base-seed 42 and 777,
  scripts/pf_batch_confirm.sh, log /tmp/pf_batch_confirm_20260814_164343.log.
  Three confirmed positive on both seeds -- **shipped True**:
    - pf3 SEMI_BLUFF_RAISE_DRAWS: +1.70 +/-0.83 (seed42, 20k hands) / +2.79
      +/-1.29 (seed777, 10k hands).
    - pf4 NUT_ADVANTAGE_SIZING: +1.95 +/-0.96 (seed42, 16k hands) / +2.00
      +/-0.99 (seed777, 14k hands) -- unusually consistent magnitude across
      seeds.
    - pf7 SPR_SCALED_THRESHOLDS: +15.32 +/-7.26 (seed42, 18k hands) / +26.20
      +/-12.58 (seed777, 14k hands) -- large and clearly positive on both
      seeds, but the magnitude itself is noisy; treat the direction as solid,
      the size as a rough estimate only.
  Four confirmed NEGATIVE on both seeds -- **stay False, do not revisit
  without a new angle**, the published theories behind them do not hold up
  against this bot's actual population mix/other rules:
    - pf1 TEXTURE_DEPENDENT_CBET_SIZING: -4.80 +/-2.57 / -6.53 +/-4.66.
    - pf6 POT_CONTROL_MARGINAL_HANDS: -7.48 +/-3.63 / -5.91 +/-3.86.
    - pf9 BLOCKER_BASED_RIVER_BLUFF: -1.24 +/-1.15 / -3.93 +/-2.36.
    - pf10 DELAYED_CBET_MARGINAL: -12.57 +/-4.77 / -21.69 +/-7.23.
  Two inconclusive (effect too small relative to CI on both seeds) --
  **stay False**, not worth the added complexity for an unconfirmed effect:
    - pf5 PROBE_BET_TURN_AFTER_CHECK: +0.21 +/-0.17 / +0.17 +/-0.09.
    - pf8 BLOCK_BET_RIVER: +0.22 +/-0.69 / +0.43 +/-0.96.
  191 tests re-run after flipping pf3/pf4/pf7 to True: still all pass.

  r22-r29 validation (2026-08-15, user asked to test everything still
  untested): same method as pf1-pf10 above, both base-seed 42 and 777,
  scripts/r22_29_batch_confirm.sh, log
  /tmp/r22_29_batch_confirm_20260815_130025.log. Four confirmed positive on
  BOTH seeds -- **shipped True**:
    - r22 THREEBET_SIZE_BY_POSITION: +6.10 +/-2.72 (seed42) / +6.91 +/-3.16
      (seed777).
    - r23 THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT: +9.18 +/-4.22 /
      +8.34 +/-3.44.
    - r24 BB_DEFEND_MDF_SCALED: +20.78 +/-7.42 / +13.74 +/-5.22 -- large
      effect both times, magnitude noisy like pf7 was.
    - r27 SET_MINE_IMPLIED_ODDS: +6.50 +/-3.00 / +9.61 +/-4.39.
  One confirmed negative on both seeds -- **stays False**:
    - r25 BLUFF_3BET_BLOCKER_RANGE_FLAG: -6.94 +/-5.07 / -4.13 +/-3.49.
  One inconclusive on both seeds -- **stays False**:
    - r28 RAKE_ADJUSTED_OPEN_SIZING: -0.02 +/-1.00 / -0.29 +/-1.00.
  Two special cases, **both stay False**, neither cleared the two-
  independent-seed bar:
    - r26 LIMP_TRAP_WITH_MONSTERS: seed42 stopped `inconclusive_small_effect`
      (+0.45 +/-0.36 at 56k hands), seed777 stopped `confirmed_positive`
      (+0.77 +/-0.38 at 64k hands) -- same sign both times, genuinely tiny
      magnitude either way (this is the natural incidence of unopened
      AA/KK, an inherently rare spot). Split verdict -- one seed didn't
      clear the bar, so this does NOT get shipped True on the strict
      both-seeds-confirmed rule used everywhere else in this file. Worth a
      bigger dedicated sample later if revisited, not urgent.
    - r29 FOLD_VS_3BET_FROM_PASSIVE: seed42 confirmed_negative (-2.15
      +/-1.22 at 84k hands, 30 divergent), but seed777 hit
      `no_divergent_hands` at the 50k cap -- zero divergent hero hands, this
      exact spot (QQ/AKs/AKo facing a 3bet+ specifically from a known
      loose-passive raiser) simply never came up naturally in that seed's
      population sample. Same `untestable_by_self_play`-style situation as
      r13's shove-vs-3bet spot noted above -- can't cross-validate a rule
      that only one seed ever exercised. The seed42 result is suggestive
      (real negative) but not confirmed by this file's own two-seed
      standard, so stays False rather than being shipped on a single
      sample.
  191 tests re-run after flipping r22/r23/r24/r27 to True: still all pass.

  2026-08-16 -- LIMP_BEHIND_OVER_LIMPERS shipped True: found during a full
  re-audit that this flag was confirmed positive back in the 2026-08-12
  r16v test (+10.3 to +10.5 bb/100 across two seeds -- see that comment
  above) but never actually flipped. Nothing about the rule changed; the
  flag itself was just wrong.

  2026-08-16 -- last remaining never-tested flags, both seeds
  (scripts/remaining_untested_confirm.sh, log
  /tmp/remaining_untested_confirm_20260816_124429.log):
  Four confirmed positive on both seeds -- **shipped True**:
    - r21 TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR: +7.90 +/-3.89 (seed42) /
      +23.26 +/-10.11 (seed777) -- noisy magnitude, solid direction.
    - v23 SIZE_UP_WITH_VERY_STRONG_HAND: +7.97 +/-3.00 / +7.22 +/-3.52.
    - v23 SIZE_UP_ON_WET_BOARD: +14.65 +/-4.44 / +12.18 +/-5.56.
    - r18v SHOVE_AA_KK_VS_3BET_PLUS, widened to
      SHOVE_VS_3BET_PLUS_RANGE={AA,KK,QQ,AKs,AKo}: +31.41 +/-14.19 /
      +15.54 +/-7.76 -- the widest tested range gave the largest and
      cleanest result; the original AA/KK-only r13 preset stays documented
      above as untestable (0 divergent even forced), the wider range is
      what actually gets exercised naturally.
    - r19v BB_DEFEND_VS_STEAL_MINRAISE, wide parameterization
      (BB_DEFEND_MAX_RAISE_BB=2.5, BB_DEFEND_VPIP_MULTIPLIER=2.0): +5.72
      +/-2.80 / +4.15 +/-1.96. The "medium" parameterization (multiplier
      1.6) got ZERO divergent hands on both seeds -- same class of dead-
      swept-parameter bug as SIZE_SCALED_CALL_RANGE and LIMP_BEHIND's
      multiplier -- and the "tight" parameterization (max_raise_bb=2.0,
      multiplier 1.3) was confirmed NEGATIVE (-4.15 +/-2.36 / -2.11
      +/-1.41). Only the wide config is shipped; this stacks on top of the
      already-True BB_DEFEND_MDF_SCALED (r24), tested against that as the
      current baseline.
  One split verdict, **stays False** -- flagged for a bigger-sample retest:
    - v27 RIVER_OVERBET_NUTS_VS_LOOSE: seed42 inconclusive_small_effect
      (+0.98 +/-0.99 at 92k hands), seed777 confirmed_positive (+3.21
      +/-1.52 at 52k hands). Leaning real but doesn't clear the strict
      both-seeds bar yet.
  One flag, all 4 parameter variants tested, **stays False** -- genuinely
  untestable at natural incidence:
    - r15v FOLD_PREMIUM_VS_EXTREME_AGGRO (fold-qq-vs-nit-tag-50,
      fold-ak-vs-nit-tag-50, fold-qq-ak-vs-nit-50, fold-qq-ak-vs-nit-tag-75):
      every variant got 0 divergent hands in 50k on both seeds. This exact
      combination (facing 2+ raises already at >=50% of hero's stack, with
      QQ/AK, against a known Nit/TAG) simply doesn't occur naturally in
      this population/stack-depth's self-play -- same situation as r13's
      AA/KK shove and r29's second-seed miss. That earlier finding is now
      also structurally true by construction, not just empirically rare:
      SHOVE_AA_KK_VS_3BET_PLUS's widened range ({AA,KK,QQ,AKs,AKo}, shipped
      True above) is checked BEFORE this branch in choose_abc_action and
      exactly covers FOLDABLE_PREMIUM_VS_EXTREME_AGGRO's hand set, so those
      hands now always shove facing 3bet+ and never reach the fold check at
      all. Effectively superseded: the data says shoving that range beats
      calling it, so folding it was never going to beat shoving it either.
      Tests updated to isolate FOLD_PREMIUM_VS_EXTREME_AGGRO by disabling
      SHOVE_AA_KK_VS_3BET_PLUS explicitly (see test_abc_bot.py).
  191 tests re-run after flipping the four winners: still all pass.

  2026-08-16, later same day -- bigger-sample retest of every remaining
  split-verdict/inconclusive flag, per explicit user request
  ("перепроверь стратегии в которых не уверен на большей выборке"). Same
  method, tighter target-CI (0.5 instead of 1.0), hand cap raised to 1M
  (`scripts/borderline_bigger_sample_confirm.sh`, log
  /tmp/borderline_bigger_sample_confirm_20260816_183316.log):
    - v27 RIVER_OVERBET_NUTS_VS_LOOSE: seed42 confirmed_positive +1.12
      +/-0.54 (288k hands -- needed real power to resolve), seed777
      confirmed_positive +4.04 +/-2.00 (36k hands). Both confirmed --
      **shipped True.**
    - r17v CALL_RANGE_BY_RAISER_POSITION: at bigger sample, BOTH seeds now
      confirmed_negative (-0.64 +/-0.63 @ 56k hands, -1.46 +/-1.11 @ 32k
      hands) -- the earlier verdict ("both land at true-zero," +0.07/-0.98
      at 1x sample) undersold it; more power reveals a real small negative,
      not a null result. **Stays False, now for a stronger reason.**
    - pf5 PROBE_BET_TURN_AFTER_CHECK: +0.24 +/-0.14 / +0.22 +/-0.13, both
      still `inconclusive_small_effect` even with target-CI halved --
      confirms this is genuinely a near-zero effect, not an
      under-powered measurement. **Stays False.**
    - pf8 BLOCK_BET_RIVER: seed42 confirmed_negative -0.78 +/-0.77 (164k
      hands), seed777 inconclusive_small_effect -0.38 +/-0.50 (348k
      hands) -- leans mildly negative now (flipped from the earlier
      +0.22 lean) but doesn't clear the bar on both seeds. **Stays
      False.**
    - r26 LIMP_TRAP_WITH_MONSTERS: seed42 inconclusive_small_effect +0.16
      +/-0.32 (92k hands), seed777 confirmed_positive +0.70 +/-0.34 (160k
      hands) -- still a split verdict even at 2-3x the earlier sample
      size. Genuinely on the edge of measurability for this rare a spot.
      **Stays False.**
  191 tests re-run after flipping RIVER_OVERBET_NUTS_VS_LOOSE: still all
  pass. This closes out the last open question from the two prior
  validation rounds -- every flag in this file now has a real, adequately-
  powered test result behind its True/False state.

  2026-08-17, overnight research pass -- user asked to (1) check whether
  the shipped iso-limper sizing and the AA/KK/QQ/AKs/AKo shove are actually
  correct against published poker theory, (2) build a small-blind-specific
  strategy (this file had never had one), (3) flatten the two ~52.5%/"~55%"
  sizing constants to a round 50% (direct instruction, not a hypothesis --
  see STANDARD_SIZING_POT_FRACTION's own comment), and (4) look harder at
  postflop for missing real spots. Researched each question against
  published sources (Upswing, PreflopWizard, 2+2, BlackRain79, PokerCoaching,
  GTO Wizard), then built and A/B-tested every resulting candidate --
  `scripts/night_research_confirm.sh`, both seeds, log
  `/tmp/night_research_confirm_20260817_071948.log`. All 12 runs resolved
  cleanly on both seeds -- no split verdicts this round:
    - r12v-published-theory (TIGHT_ISO base=4.0bb/per-limper=1.0bb, matching
      the "3-4bb + 1bb/limper" published convention, vs. the shipped
      5.5bb/1.5bb): confirmed NEGATIVE both seeds, -30.24 +/-5.45 (seed42) /
      -39.23 +/-7.21 (seed777). The shipped sizing, despite being well above
      any published number, is genuinely better against THIS population --
      published theory assumes real opponents adjusting to bet sizing (fewer
      cold-calls at bigger sizes); this bot's ML opponents don't model that
      the same way. **No change** -- TIGHT_ISO_BASE_SIZING_BB/_PER_LIMPER_BB
      stay at 5.5/1.5.
    - SIZED_4BET_INSTEAD_OF_SHOVE (~2.3x IP / ~2.6x OOP sized 4-bet instead
      of shoving the SHOVE_AA_KK_VS_3BET_PLUS range all-in, matching
      published 100bb-effective 4-bet theory): confirmed NEGATIVE both
      seeds, -9.62 +/-5.81 (seed42) / -2.16 +/-2.02 (seed777). The all-in
      shove -- itself already confirmed better than flat-calling -- beats a
      smaller sized 4-bet too. **Stays False**, SHOVE_AA_KK_VS_3BET_PLUS's
      existing all-in sizing is unchanged.
    - SB_BIGGER_OPEN_SIZING (open 3bb instead of 2.5bb from SB in the
      blind-vs-blind case): inconclusive both seeds, +0.19 +/-0.13 (seed42)
      / +0.04 +/-0.09 (seed777) -- genuinely near-zero. **Stays False.**
    - SB_THREEBET_OR_FOLD_VS_STEAL (3-bet the whole continue range facing a
      CO/BTN/SB steal instead of ever flat-calling): confirmed POSITIVE both
      seeds, +4.10 +/-2.00 (seed42) / +5.91 +/-2.76 (seed777). **Shipped
      True** -- this file's first-ever SB-specific rule.
    - FOLD_MARGINAL_VS_CHECK_RAISE (fold a plain top-pair hand to a genuine
      check-raise, heads-up, non-loose aggressor -- published micro-stakes
      theory says check-raises there skew value-heavy): confirmed NEGATIVE
      both seeds, -0.37 +/-0.16 (seed42, 388k hands) / -0.56 +/-0.28
      (seed777, 374k hands) -- both needed hundreds of thousands of hands
      since a genuine check-raise is a rare event in this bot's self-play.
      The published exploit doesn't transfer to this specific ML-bot
      population -- plausibly because these bots' check-raise frequency/
      composition isn't modeling the same real-population skew the
      published advice is based on. **Stays False** -- same "standard
      theory doesn't always transfer to this specific population" pattern
      this file's history keeps returning to (MULTIWAY_AWARE,
      UNCONDITIONAL_FLOP_CBET's own test, VALUE_RAISE_FACING_BET, etc.).
    - FLOAT_FLOP_IN_POSITION (call a flop bet in position with no hand/draw,
      bet the turn if checked to again): confirmed POSITIVE both seeds,
      +8.10 +/-3.20 (seed42) / +9.35 +/-4.35 (seed777). **Shipped True.**
  Net result: 2 new rules shipped True (SB_THREEBET_OR_FOLD_VS_STEAL,
  FLOAT_FLOP_IN_POSITION), 4 hypotheses tested and rejected with real
  numbers behind the rejection (not just "untested"). 191 tests re-run
  after flipping the two winners: still all pass, checked across multiple
  random PYTHONHASHSEED values (a real, unrelated test-fragility bug was
  found and fixed the same night -- see test_tight_big_iso_folds_plain_
  open_hands_outside_tight_iso_range's history in tests/test_abc_bot.py --
  that test's `next(iter(a_set))` pick was hash-seed-dependent and could
  land on a hand LIMP_BEHIND_OVER_LIMPERS legitimately calls with instead
  of folding; fixed to a deterministic sorted() pick that also excludes the
  limp-behind range explicitly).

  Postflop gap audit (same night, not all acted on): reading through
  choose_abc_action end-to-end surfaced several more real, disclosed gaps
  beyond the two closed above -- no response to a donk lead specifically
  while hero HAS initiative (currently identical to any other "facing a
  bet"), no board-texture-aware discount on calling `made` hands (a plain
  top pair calls a big bet on a 4-flush river exactly like it calls on a
  dry one, FOLD_TOP_PAIR_VS_OVERBET only gates on bet SIZE not board
  danger), and no "give up vs. keep firing" decision for a missed draw on
  the river (should_call_with_draw correctly never calls there, but there's
  no bluff option either). None implemented tonight -- flagged here as real
  future candidates, not invented and forgotten.

  2026-08-17, later same day -- the three postflop gaps above, closed.
  Same discipline: research first, off-by-default flag, then A/B test both
  seeds. `scripts/postflop_gaps_confirm.sh`, log
  `/tmp/postflop_gaps_confirm_20260817_140539.log`:
    - FOLD_MARGINAL_VS_BIG_DONK (fold a plain top-pair hand to a BIG,
      >=66% pot, donk lead specifically while hero has preflop initiative --
      published theory says a big donk into the raiser skews more toward
      real value than a small one): confirmed NEGATIVE both seeds, -0.77
      +/-0.31 (seed42, 92k hands) / -0.70 +/-0.28 (seed777, 108k hands).
      **Stays False** -- third rejected "add more theory-based folding"
      idea this same night (after FOLD_MARGINAL_VS_CHECK_RAISE), a
      consistent pattern for this population, not a one-off.
    - FOLD_TOP_PAIR_VS_WET_BOARD_TIGHT (fold a plain top-pair hand to a
      real-sized bet on a wet board specifically from a known tight
      archetype, gated to TIGHT_ARCHETYPES_FOR_DONK_BLUFF so it can't touch
      LOOSE_ARCHETYPES' own opposite-direction any-pair-or-better rule):
      confirmed NEGATIVE both seeds, -1.13 +/-0.43 (seed42, 78k hands) /
      -1.51 +/-0.58 (seed777, 56k hands). **Stays False** -- fourth
      rejected folding idea tonight. Board-texture-aware folding, like
      check-raise-aware folding, does not transfer to this specific ML-bot
      population even though both are standard published advice.
    - RIVER_BLUFF_MISSED_DRAW (bet the river as a bluff, 66% pot, when
      checked to after a real flush/straight draw hero held just missed,
      gated to known tight archetypes): confirmed POSITIVE both seeds,
      +1.78 +/-0.88 (seed42, 218k hands) / +2.95 +/-1.45 (seed777, 94k
      hands). **Shipped True** -- unlike the two folding ideas above, this
      is a new BETTING line (a missing decision category, not a range/
      threshold tweak), consistent with this file's long-standing pattern
      that new lines beat range/threshold theory-matching.
  Net for this batch: 1 shipped True (RIVER_BLUFF_MISSED_DRAW), 2 tested
  and rejected with real numbers. Combined with the overnight pass above,
  this closes out every postflop gap identified in the 2026-08-17 audit.
  Fixed one more hash-seed test-fragility instance found while re-checking
  the whole suite (test_does_not_isolate_a_limper_wider_when_flag_off had
  the same next(iter(a_set)) issue as the one fixed earlier that night);
  swept the rest of tests/test_abc_bot.py for the same pattern preemptively
  (4 more occurrences converted to a deterministic sorted() pick). 191
  tests pass across 5 different random PYTHONHASHSEED values.

  2026-08-17, later same session -- 4 follow-up ideas raised while
  explaining preflop/postflop strategy to the user, all tested via
  scripts/followup_ideas_confirm.sh, log
  /tmp/followup_ideas_confirm_20260817_164109.log, both seeds:
    - SB open 3.5bb (re-testing SB_BIGGER_OPEN_SIZING at a bigger step
      than the already-tested 3.0bb): inconclusive both seeds, +0.27
      +/-0.15 (seed42) / +0.08 +/-0.10 (seed777) -- even tighter around
      zero than 3.0bb. Confirms this isn't a step-size artifact. Stays
      False.
    - TIGHT_BIG_ISO_RAISE_LIMPERS vs ISO_WIDER_RANGE_OVER_LIMPERS, real
      head-to-head (found while explaining the code that ISO_WIDER's own
      branch has been structurally dead since TIGHT_BIG_ISO shipped --
      see ISO_WIDER_RANGE_OVER_LIMPERS's own comment for the full story):
      confirmed NEGATIVE both seeds for ISO_WIDER as the live mechanism,
      -14.19 +/-11.63 (seed42) / -33.94 +/-17.01 (seed777). Today's
      default (TIGHT_BIG_ISO_RAISE_LIMPERS) is genuinely better, not just
      winning by code priority accident. ISO_WIDER_RANGE_OVER_LIMPERS
      flipped to False (no behavior change, it was already unreachable --
      this just makes the flag's value stop lying about being a live,
      strong lever).
    - SB flat-call vs fold diagnostic (does SB_THREEBET_OR_FOLD_VS_STEAL's
      win mask a postflop game too weak to play ANY OOP continue
      profitably?): confirmed NEGATIVE both seeds for folding, -9.58
      +/-4.37 (seed42) / -4.82 +/-2.53 (seed777) -- i.e. flat-calling
      clearly beats folding. SB's call range is solidly +EV against a
      steal in absolute terms; 3-betting simply beats an already-
      profitable call, it isn't rescuing an unprofitable one. Diagnostic-
      only flag (SB_FOLD_VS_STEAL_DIAGNOSTIC), stays False either way.
    - Narrow the tight-iso range further per limper beyond the first
      (TIGHT_ISO_TIGHTENS_PER_EXTRA_LIMPER, only sizing scaled with
      n_limpers before): confirmed NEGATIVE both seeds, -5.98 +/-3.29
      (seed42) / -14.42 +/-6.09 (seed777). Further narrowing hurts --
      today's fixed-range-plus-bigger-sizing approach is already correct.
      Stays False.
  All 4 resolved cleanly on both seeds, no split verdicts. Net: 0 new
  flags shipped True, 1 stale/misleading flag corrected (ISO_WIDER_RANGE_
  OVER_LIMPERS), 3 honest negative findings that rule out real concerns
  (SB open sizing isn't under-stepped, SB flat-calling isn't a symptom of
  weak OOP postflop, tighter-per-limper isolation doesn't help). 191 tests
  pass across multiple PYTHONHASHSEED values after these changes.

  2026-08-17, one more round: user asked "what else globally needs
  checking" -- answer included the three MULTIWAY_* sub-flags (MULTIWAY_
  NARROW_CALL_RANGE, MULTIWAY_DISABLE_AIR_CBET, MULTIWAY_DISABLE_LOOSE_
  CALL), initially described as "never individually tested" -- WRONG, v18
  (2026-08-07, see that changelog entry) already tested all three
  individually with the old whole-game simulation method. Corrected
  immediately on re-reading this file's own history. Two of the three had
  clean old-method separation from zero (disable-air-cbet -7.94, disable-
  loose-call -5.91); MULTIWAY_NARROW_CALL_RANGE was explicitly borderline
  (-3.96 with rake, +1.04 without -- inside/at the edge of CI), the same
  situation as SIZE_UP_PREMIUM_OPENS before its chance-enumeration re-
  check reversed the old imprecise verdict. Re-ran all three with the
  modern method anyway for a clean cross-check, scripts/multiway_
  subflags_recheck.sh, log
  /tmp/multiway_subflags_recheck_20260817_171917.log, both seeds:
    - MULTIWAY_DISABLE_AIR_CBET: confirmed NEGATIVE both seeds, -24.96
      +/-8.02 (seed42) / -44.70 +/-10.93 (seed777).
    - MULTIWAY_DISABLE_LOOSE_CALL: confirmed NEGATIVE both seeds, -29.70
      +/-7.94 (seed42) / -26.51 +/-7.36 (seed777).
    - MULTIWAY_NARROW_CALL_RANGE (the one borderline case): confirmed
      NEGATIVE both seeds, -36.83 +/-11.79 (seed42) / -29.68 +/-8.90
      (seed777) -- resolves cleanly this time, no ambiguity left.
  Unlike SIZE_UP_PREMIUM_OPENS, the modern method did NOT reverse this
  verdict -- v11/v18's original finding holds up under much lower
  variance too. All three stay False; this closes the multiway-awareness
  question with real confidence instead of one imprecise whole-game
  sample. If multiway-specific strategy is ever revisited, per this
  file's own C1/C2 pattern the productive angle is a genuinely NEW
  behavior for multiway pots, not further restricting the existing three.

  2026-08-18, one more round: pushed the two remaining borderline results
  from the 2026-08-16 bigger-sample round (r26-limp-trap-monsters,
  pf8-block-bet-river) to a tighter target-CI (0.25 vs the earlier 0.5),
  same 1M-hand cap. scripts/borderline_bigger_sample_round2.sh, log
  /tmp/borderline_bigger_sample_round2_20260817_175050.log, both seeds:
    - BLOCK_BET_RIVER: -0.73 +/-0.70 (seed42, 172k hands, confirmed_
      negative) / -0.39 +/-0.39 (seed777, 492k hands, confirmed_
      negative) -- NOW CONFIRMED NEGATIVE ON BOTH SEEDS. The earlier
      round's seed777 run (-0.38 +/-0.50, inconclusive) just hadn't run
      long enough to clear the bar; more precision resolved it cleanly.
      Stays False, now with real confidence instead of "leans negative."
    - LIMP_TRAP_WITH_MONSTERS: +0.16 +/-0.24 (seed42, 136k hands,
      inconclusive_small_effect) / +0.69 +/-0.34 (seed777, 160k hands,
      confirmed_positive) -- STILL SPLIT, and now a more interesting
      split than before: at this tighter precision the two point
      estimates (0.16 vs 0.69) actually disagree with EACH OTHER beyond
      their own combined CI (0.53 gap vs sqrt(0.24^2+0.34^2)=0.42
      combined) -- not just "both too imprecise to call," but real
      between-sample inconsistency for this specific rare spot (unopened
      AA/KK only). Honest read: if there's a true effect here it's small
      (roughly 0-0.7 bb/100) and/or genuinely variable in a way this
      probe's methodology doesn't capture (e.g. real opponent-mix
      variance hand-to-hand rather than pure sampling noise) -- further
      hand-count increases alone are unlikely to resolve this cleanly,
      diminishing returns past this point. Stays False, unresolved by
      design rather than by neglect.
  191 tests unaffected (no flag defaults changed this round -- both were
  already False and stay False).

  2026-08-18, same session: picked up TURN_OVERBET_NUTS_VS_LOOSE, a
  generalization of RIVER_OVERBET_NUTS_VS_LOOSE (v27) off "river only" --
  that restriction was never itself a tested finding, just where the
  overbet-with-near-nuts-vs-loose-archetype idea was first tried. Two
  other candidates from the same "what else needs checking" pass were
  scoped and set aside instead of built: per-opponent (not archetype-
  level) bluff-frequency exploitation needs session-continuity simulation
  this project's precision test harness doesn't have (TableDossier's
  per-seat stats accumulate across many hands at one table;
  probe_chance_enumeration.py samples one fresh hand at a time) -- a
  real infrastructure gap, not a quick check; tilt/bad-beat state-change
  detection has no groundwork in either repo, would need fresh research
  against the real dataset first. scripts/turn_overbet_confirm.sh, log
  /tmp/turn_overbet_confirm_20260818_140943.log, both seeds -- confirmed
  POSITIVE both seeds, resolved unusually fast (10k/16k hands):
    - seed42: +1.86 +/-0.84 bb/100
    - seed777: +1.69 +/-0.81 bb/100
  Consistent magnitude between seeds, clean result. Shipped True. 191
  tests pass across multiple PYTHONHASHSEED values after flipping it.

  2026-08-18, same session: two more candidates from the "what else can
  be checked" list, both flagged as separate untested questions in this
  file's own comments when their sibling rules shipped.
  scripts/semibluff_turn_wetboard_confirm.sh, log /tmp/semibluff_turn_
  wetboard_confirm_20260818_150344.log, both seeds:
    - SEMI_BLUFF_RAISE_DRAWS_TURN (extends pf3's flop-only semi-bluff
      raise to the turn -- flagged when pf3 shipped as "semi-bluff-
      raising a turn draw commits far more with one card left, a bigger
      and separately-untested question"): confirmed POSITIVE both seeds,
      +1.91 +/-0.95 (seed42, 216k hands) / +2.08 +/-1.04 (seed777, 218k
      hands). Turned out the extra-commitment risk didn't outweigh the
      fold-equity/backup-equity gain -- same direction and similar
      magnitude as the flop version. Shipped True.
    - SMALLER_BLUFF_ON_WET_BOARD (the flip side of SIZE_UP_ON_WET_BOARD --
      size a plain air bluff, i.e. cbet_with_air/donk_bluff_with_air/
      barrel_bluff_with_air, SMALLER on a wet board instead of standard,
      flagged as a separate untested question when v23 shipped): confirmed
      NEGATIVE both seeds, -4.07 +/-3.72 (seed42, 8k hands) / -4.46
      +/-3.78 (seed777, 10k hands). A cheaper bluff on a wet board loses
      more fold equity than it saves in chips -- consistent with this
      file's broader pattern that this population doesn't fold to size
      the way solver-derived sizing theory assumes. Stays False.
  191 tests pass across multiple PYTHONHASHSEED values after flipping
  SEMI_BLUFF_RAISE_DRAWS_TURN.

  2026-08-19/20: MAJOR restructure, user-directed -- opponent
  classification split into two independent axes instead of one flat
  archetype label. PokerDom_Microlimits_Analysis/src/pipeline/
  archetypes.py: (1) new `postflop_freq_tier` (rare/normal/often, from
  the same aggression_factor stat, literature-grounded AF thresholds
  <2.0/2.0-3.0/>3.0), (2) the archetype function itself made PURELY
  preflop -- it used to gate Maniac on postflop af>=2.0, mixing the two
  axes; redefined as vpip>0.45 and pfr_ratio>=0.45 (no af parameter at
  all). Real population shift: Maniac 3352 -> 756 players (12.5% ->
  2.8%), absorbed mostly into Station/Loose-passive. Full cascade
  rebuilt per user's "нужно вообще всё переделать под новые типы":
  all 4 archetype_*.csv reference tables, matchup_hand_ev.csv (all 36
  pairs), player_profile_seeds.csv, the ML opponent training dataset
  (34.5M rows) and BOTH CatBoost models retrained, session-length-by-
  archetype data, and ARCHETYPE_POPULATION_WEIGHTS in live_dynamics.py.
  Old models backed up before overwriting. 191 tests + a whole-game
  smoke test (5000 hands) both clean after the retrain, +22.45+/-10.79
  bb/100 excl. monster pots -- the strategy is not broken against the
  new population.

  First re-validation round against the new population/model
  (scripts/repop_revalidate_round1.sh, log
  /tmp/repop_revalidate_round1_20260820_005*.log, both seeds) --
  prioritized the single biggest lever in the file plus the one flag
  whose loose-archetype set explicitly includes Maniac:
    - OPPONENT_AWARE_ARCHETYPES (v10): still confirmed POSITIVE both
      seeds, +47.01+/-11.91 (seed42) / +59.24+/-13.91 (seed777) -- the
      biggest lever in the file survives the restructure intact. Makes
      sense in hindsight: LOOSE_ARCHETYPES's three-archetype total
      (Loose-passive+Station+Maniac) barely moved in aggregate (18,360
      -> 18,542 of 26,797 players) even though Maniac specifically
      shrank a lot -- the reclassified players landed in the other two
      members of the same set.
    - WIDER_3BET_VS_LOOSE (v15/B1): previously "active but unconfirmed"
      (old whole-game method, +1.62 @500k, inside CI) -- NOW confirmed
      POSITIVE both seeds with the modern method, +4.91+/-2.43 (seed42)
      / +5.99+/-2.72 (seed777). Resolves this Tier-1 backlog item at the
      same time as the population re-check.
  Everything else in the file's confirmed-flag history has NOT yet been
  re-validated against the new population -- flagged in memory as a
  large, ongoing, multi-session task, not attempted exhaustively in one
  sitting.

  Second re-validation round (scripts/repop_revalidate_round2.sh, log
  /tmp/repop_revalidate_round2_20260820_012413.log, both seeds) --
  covered every OTHER shipped-True flag that reads an opponent
  archetype-set membership, per user instruction "нужно проверить все
  флаги зависящие от типа игроков у нас же теперь они новые":
    - FLOAT_FLOP_IN_POSITION: confirmed POSITIVE both seeds, +7.15+/-3.00
      (seed42) / +11.51+/-4.78 (seed777).
    - BLUFF_3BET_VS_TIGHT (v24): confirmed POSITIVE both seeds with the
      modern method for the FIRST time ever (previously only the old
      whole-game method had tested it, +1.80 bb/100 @2M/arm) --
      +3.85+/-1.91 (seed42) / +5.42+/-2.60 (seed777).
    - DONK_BLUFF_VS_TIGHT (r10/v17): confirmed POSITIVE both seeds,
      +1.25+/-0.61 (seed42) / +2.47+/-1.23 (seed777).
    - BARREL_BLUFF_VS_TIGHT (v25): confirmed POSITIVE both seeds,
      +3.89+/-1.82 (seed42) / +6.94+/-3.44 (seed777).
    - RIVER_BLUFF_MISSED_DRAW: confirmed POSITIVE both seeds,
      +2.03+/-0.98 (seed42) / +2.85+/-1.36 (seed777).
    - RIVER_OVERBET_NUTS_VS_LOOSE (v27): direction still positive both
      seeds, but WEAKER than pre-restructure -- seed42 landed
      +0.94+/-0.83 (inconclusive_small_effect, CI barely clears zero),
      seed777 +3.74+/-1.85 (confirmed_positive). Not a clean both-seeds
      re-confirmation by this file's own bar; stays True on the strength
      of two-for-two positive direction plus the original pre-restructure
      confirmation, but flagged for a bigger-sample re-check rather than
      treated as fully re-validated.
    - TURN_OVERBET_NUTS_VS_LOOSE: same pattern, weaker than pre-
      restructure -- seed42 +0.35+/-0.93 (inconclusive_small_effect, CI
      crosses zero), seed777 +1.88+/-0.93 (confirmed_positive). Same
      caveat as RIVER_OVERBET_NUTS_VS_LOOSE above.
    - STEAL_WIDER_VS_NIT / SIZING_TARGET_ARCHETYPES (v14): both hit ZERO
      divergent hands in 100k on BOTH seeds -- still untestable by self-
      play at the current population/model, same limitation as before
      the restructure (TIGHT_ARCHETYPES_FOR_STEAL={"Nit"} is a rare-
      opponent-behavior bottleneck, not a hero-hand one). Stays an open
      Tier-1 backlog item, unresolved either way.
  Net: 5/9 flags cleanly re-confirmed, 2/9 hold direction but weakened
  (worth a bigger-sample follow-up), 2/9 remain untestable by self-play
  regardless of population. No flag flipped sign or was disabled this
  round.

  2026-08-20, postflop_freq_tier retrain: after landing the infra-only
  step (live tier assignment + opponent_freq_tiers plumbing through
  choose_abc_action, no rule reads it), the ML opponent model
  (behavior_clone.py) was retrained WITH freq_tier added to
  CAT_FEATURES (see that file's own comment). build_training_data.py now
  carries each real player's own measured postflop_freq_tier alongside
  their archetype -- ground truth, not a population sample, since we
  already know that specific real player's aggression_factor. Old
  models backed up first. Losses improved slightly over the archetype-
  only retrain (action bestTest 0.6699 -> 0.6675, sizing 0.5909 ->
  0.5900) -- a small but real signal, not noise. 191 tests pass across 3
  PYTHONHASHSEED values, 5000-hand whole-game smoke test clean
  (+33.26+/-11.28 bb/100 excl. monster pots, better than the +22.45
  archetype-only-retrain baseline, no crash). Direct sanity check
  confirms the model actually learned the signal: same archetype
  (Station) and decision point, raise probability rises monotonically
  with tier -- rare 4.5% -> normal 6.4% -> often 7.5%.

  STILL NOT DONE (as of the retrain above): no hero rule in this file
  reads opponent_freq_tiers yet. The opponent MODEL now behaves
  differently by tier, but hero doesn't yet exploit that -- designing
  and testing a freq-tier-aware rule is the next real step, not started.

  2026-08-20, WIDER_CALL_VS_OFTEN_TIER: the first rule to close that gap.
  Generalizes the LOOSE_ARCHETYPES any-pair-or-better call across the
  freq_tier axis -- OR'd with the existing archetype check, either being
  true is enough to widen (see the flag's own comment for the full
  reasoning). Confirmed POSITIVE both seeds, +22.27+/-7.39 (seed42) /
  +11.24+/-5.51 (seed777). Shipped True. 191 tests pass across 3
  PYTHONHASHSEED values, 5000-hand smoke test clean and improved further
  (+38.47+/-11.76 bb/100 excl. monster pots, up from +33.26 pre-flag).

  2026-08-21, pokerdom_pending_ideas backlog cleanup (scripts/
  pending_backlog_round1.sh, bigger-N budgets, both seeds where
  applicable):
    - USE_WIDE_VALUE_3BET (v9): last remaining Tier-1 "old whole-game
      method only" item. CONFIRMED POSITIVE both seeds with the modern
      method, +6.73+/-2.88 (seed42) / +3.60+/-1.78 (seed777). No longer
      pending.
    - FOLD_VS_3BET_FROM_PASSIVE (r29): previously one seed confirmed
      negative, one seed zero divergent hands (never cross-validated).
      Re-run with a 300k-hand budget: ZERO divergent hands on BOTH seeds
      now -- confirmed untestable by self-play at the current population/
      model, same class as STEAL_WIDER_VS_NIT. Stays False, no longer an
      open cross-validation question (it's a genuine self-play blind
      spot, not unresolved).
    - OPTIMAL_VALUE_SIZING_PER_ARCHETYPE (v28): magnitude was fuzzy
      (+0.68 to +4.88 bb/100 across 5 samples, sign always positive).
      Pinned down with one big run (90k hands, target_ci=0.5,
      3035 divergent hands): +1.39+/-0.79 bb/100. Resolves the backlog
      item.
    - RIVER_OVERBET_NUTS_VS_LOOSE / TURN_OVERBET_NUTS_VS_LOOSE: the
      round-2 re-validation (2026-08-20) found these weaker than pre-
      restructure but still nominally positive both seeds. Re-run here
      with a much bigger budget (up to 144k hands): direction STILL
      positive both seeds, but the magnitude has converged close to zero
      (river: +0.51+/-0.98 / +0.98+/-0.83; turn: +0.72+/-0.57 /
      +0.59+/-0.53) -- both landed stop_reason=inconclusive_small_effect
      even at this sample size, not just noise from a small run. Real
      finding: whatever edge these had pre-restructure has largely
      evaporated under the new archetype/model population. Both stay
      True (no evidence of active harm, and flipping on a
      near-zero-but-still-positive point estimate isn't warranted
      either) but should not be cited with their old magnitudes anymore.
  191 tests pass, 5000-hand smoke test unaffected (no flag changed
  direction).

  2026-08-21, Tier-5 confirmation (scripts/tier5_confirm.sh, both seeds):
    - FLOAT_TURN_IN_POSITION: confirmed POSITIVE both seeds, +15.76+/-7.69
      (seed42) / +10.28+/-4.86 (seed777). Shipped True.
    - SIZE_UP_PREMIUM_3BETS: confirmed NEGATIVE seed42 (-1.80+/-1.63),
      inconclusive-but-negative-leaning seed777 (-0.50+/-0.98). Unlike
      SIZE_UP_PREMIUM_OPENS, sizing up a value 3-bet with a premium hand
      does NOT help -- a 3-bet already telegraphs strength, so the extra
      size likely just makes it easier for the raiser's continuing range
      to fold profitably rather than pay off. Stays False, tested-and-
      rejected. 191 tests pass, 5000-hand smoke test improved further
      (+40.75+/-11.23 bb/100 excl. monster pots, up from +38.47).

  2026-08-21, Tier 4 groundwork -- tilt-after-cooler infra, harder of the
  two Tier 4 items (user's explicit choice over the freq_tier-style
  static-label shortcut for the other Tier 4 idea, per-opponent bluff
  frequency, which stays untouched). Third session-scoped signal, but
  unlike archetype/freq_tier this one genuinely changes hand-to-hand:
    - live_dynamics.py: TableTurnover now tracks each seat's
      hands_since_cooler across the session (SeatOccupant field, reset on
      re-seating). New TableTurnover.record_hand_for_tilt(hand), called
      once per finished hand alongside the existing after_hand() turnover
      check, detects a cooler (>=15bb invested, real showdown reached,
      lost -- exact same definition and constants as
      PokerDom_Microlimits_Analysis/scripts/check_tilt_after_cooler.py)
      and updates the window. tilt_tier_for(seat) buckets into
      none/acute(1-2)/fading(3-5)/residual(6-10), matching that script's
      own decay-curve finding.
    - build_training_data.py: reuses that same script's cached per-
      (hand,player) hands_since_cooler computation (768,494 post-cooler
      pairs) rather than recomputing -- causally safe as a training
      feature since it only depends on that player's OWN past hands.
    - behavior_clone.py/train_behavior_clone.py: CAT_FEATURES gained
      "tilt_tier". Retrained (old models backed up first) -- losses
      barely moved (action 0.6675->0.6672, sizing 0.5900->0.5905, both
      within noise, expected since tilt_tier is nonzero for only ~2.2% of
      rows) but a direct sanity check confirms the model DID learn the
      real-data direction: at a fixed decision point, call probability
      rises (24.1%->26.4%) and fold probability drops (70.7%->67.5%) the
      moment tilt_tier leaves "none" -- matches the real +11.75pp VPIP
      finding. The finer acute/fading/residual gradient didn't show up
      distinctly at that one test point; the tilting-vs-not split clearly
      did.
    - choose_abc_action gained an opponent_tilt_states param, documented
      as unused so far -- same infra-first pattern as opponent_freq_tiers.
    - backend/api.py + 6 scripts wired to call record_hand_for_tilt() and
      pass tilt_tier through to choose_bot_action.
  191 tests pass, 5000-hand smoke test clean (+40.90+/-11.00 bb/100 excl.
  monster pots, unchanged from pre-tilt-retrain -- expected, nothing
  reads opponent_tilt_states yet).

  STILL NOT DONE at the time of the retrain above:
  probe_chance_enumeration.py starts every probed hand fresh (documented
  in its own module docstring) -- it has no way to simulate a SEQUENCE of
  hands per opponent, so there's currently no way to A/B test a hero rule
  that exploits opponent_tilt_states the way it actually works live (need
  a cooler to occur, then observe the following ~10 hands).

  2026-08-21, WIDER_CALL_VS_TILTING_OPPONENT: rather than build that full
  sequence infrastructure, tested via ground-truth PER-HAND sampling from
  the real population incidence instead (same "ceiling before estimation
  noise" precedent as archetype/freq_tier's first tests) -- see the
  flag's own comment for the full reasoning and disclosed limitation.
  Result: seed42 confirmed_positive, +0.70+/-0.30 bb/100 (124k hands, 30
  divergent) -- seed777 hit ZERO divergent hands at a 300k-hand budget.
  NOT cross-validated per this file's own two-seed standard. Stays False
  -- same single-seed-signal/single-seed-silent pattern
  FOLD_VS_3BET_FROM_PASSIVE originally showed. 191 tests pass, no
  behavior change (flag off).

  2026-08-22, the sequence-of-hands simulator DOES get built: turned out
  not to need new architecture -- _run_probe_chunk already keeps the same
  TableTurnover object alive across its whole n_hands loop (only the
  Table's STACKS reset every hand, not opponent identity/session state).
  Added one call, `turnover.record_hand_for_tilt(hand)`, right after
  each hand that genuinely finishes (guarded on Hand.finished, which
  naturally excludes divergent hands -- their delta computation forks
  into separate copies via _continue_to_finish instead, so there's no
  ambiguity about which hypothetical outcome should update a shared,
  persistent turnover). opponent_tilt_states now reads
  turnover.tilt_tier_for(seat) directly (live accumulated history)
  instead of sampling. Incidence jumped ~8x (0.20% vs 0.024% divergent
  hero hands) and seed42 re-confirmed much faster: +3.16+/-1.34 bb/100
  (16k hands, 32 divergent, scripts/tilt_confirm_live.sh). seed777 AGAIN
  found zero divergent hands (150k budget) -- a separate diagnostic
  confirmed this isn't a plumbing bug (tilt state actually fires in ~25%
  of that seed's seat-hands, MORE than seed42's ~14%); more likely the
  seats that end up tilting in seed777's population draw already qualify
  via LOOSE_ARCHETYPES/WIDER_CALL_VS_OFTEN_TIER, masking any marginal
  tilt-only effect. Still not cross-validated. WIDER_CALL_VS_TILTING_
  OPPONENT stayed False at this point.

  2026-08-22 CORRECTION AND FINAL RESULT: found and fixed a real bug
  right after the result above -- probe_chance_enumeration.py's OPPONENT
  bots' own choose_bot_action calls never actually passed tilt_tier
  (only hero's ground-truth read via opponent_tilt_states did), so
  seated opponents never behaved differently while tilting during either
  test -- only their LABEL said so. Both prior seed42-only signals were
  most likely noise from a mechanism that couldn't exist with opponent
  behavior held constant. Fixed (opponent bots now read tilt_tier same
  as archetype/freq_tier) and RE-TESTED (scripts/tilt_and_bluff_
  confirm.sh): CONFIRMED POSITIVE both seeds this time,
  +2.60+/-1.06 (seed42, 34k hands, 32 divergent) / +3.09+/-1.31
  (seed777, 22k hands, 32 divergent). WIDER_CALL_VS_TILTING_OPPONENT
  shipped True. 191 tests pass, 5000-hand smoke test improved
  (+45.53+/-12.26 bb/100 excl. monster pots, up from +33.48 pre-flag).

  Also built (same retrain) the OTHER Tier 4 idea: per-opponent bluff
  frequency. PokerDom_Microlimits_Analysis/scripts/find_frequent_
  bluffers.py's original definition (last river aggressor reaches real
  showdown and loses) only reliably covers 49/26,797 players (0.2%) even
  on the full dataset -- too thin to build a tier distribution the way
  archetype/freq_tier/tilt all could. Per user's "build both, compare"
  instruction, built a SECOND competing definition (bluff_tier_c: ANY-
  street aggressor reaching a real showdown and losing, a broader but
  less precise proxy) alongside the original (bluff_tier_a) --
  scripts/compare_bluff_frequency_variants.py in the analysis project.
  Variant C covers 7,974/26,797 (29.8%), ~10x better. Both wired all the
  way through (live_dynamics.py population sampling, build_training_
  data.py real-player lookup, CAT_FEATURES, retrain, choose_abc_action
  params, two candidate hero rules BLUFF_CATCH_VS_FREQUENT_BLUFFER_A/C).
  BOTH stayed untestable even at a 150k-hand-per-seed budget -- zero
  divergent hands, both seeds, both variants. Better coverage alone
  didn't fix it: the real bottleneck is COMPOUND rarity (aggressor +
  "high" tier + hero holding a qualifying hand not already covered by
  archetype/freq_tier/tilt). Both stay False.

  2026-08-22, Tier 6 backlog (user: "давай отдельно сделаем вариант а и
  с" then "делай всё по очереди" -- all four brainstorm items, taken in
  order): scripts/tier6_confirm.sh, both seeds.
    - MULTIWAY_TIGHTEN_VS_SHORT_STACK_BEHIND (#1, relative stack among
      multiple opponents): ZERO divergent hands both seeds (150k
      budget). Genuinely untestable, same class as STEAL_WIDER_VS_NIT --
      the compound spot (multiway + would-be-widened call + a specific
      other opponent short-stacked) is too rare.
    - CONTINUOUS_FOLD_VS_BET_SIZE (#4, graduated fold probability
      instead of a hard size cutoff): confirmed NEGATIVE both seeds,
      -0.82+/-0.33 (seed42) / -0.57+/-0.22 (seed777). A genuinely
      different mechanism landed in the same place every other
      "fold more to bet size" idea in this file has -- this population
      doesn't punish oversized bets the way theory predicts, regardless
      of how the trigger is shaped. Tested-and-rejected.
  191 tests pass, no behavior change (both flags off).

  2026-08-22, Tier 6 #2 (CONFIDENCE_GATED_ARCHETYPE_READ): tested via
  scripts/confidence_gate_confirm.py (special many-short-independent-
  sessions method -- see that script's docstring for why the normal
  long-adaptive-run harness structurally can't reach the low-confidence
  window). Confirmed NEGATIVE both seeds, -32.67+/-10.06 (seed42) /
  -29.75+/-8.64 (seed777). Real structural finding: opponent_archetypes
  is always ground truth in this self-play sim from hand 1 -- there's no
  actual estimation noise for "confidence" to protect against, so
  distrusting an already-100%-accurate read only discards real value.
  Would need testing against a genuinely noisy read (e.g. the live app's
  dossier estimate) to have any chance of showing an effect -- out of
  scope for this probe's ground-truth-everywhere design. Stays False.

  2026-08-22, Tier 6 #3 (REAL_RANGE_NUT_ADVANTAGE_SIZING): found
  PokerDom_Microlimits_Analysis's src/engine/range_equity.py already
  exists, tested, and is used by the live EV panel -- not a from-scratch
  build. Wired a real Monte Carlo range-vs-range equity read (hero's
  opening range vs the opponent's implied continuing range, on the
  actual board) in as an alternative to NUT_ADVANTAGE_SIZING's binary
  (top-card-rank, wet/dry) proxy, independently toggleable. Tested
  (scripts/real_range_confirm.sh): ZERO divergent hands on BOTH seeds at
  150k hands each (~52 minutes total -- Monte Carlo equity runs ~13ms/
  hand here, an order of magnitude slower than most presets). Since
  NUT_ADVANTAGE_SIZING is already True in both arms, divergence only
  happens where the real equity read disagrees with the proxy -- and on
  this population, at this threshold, it apparently never does. Real
  finding: the cheap proxy already captures essentially everything the
  expensive calculation would add to this specific binary decision.
  Stays False.

  This closes out the full Tier 6 backlog (#1-#4, all taken in order per
  the user's "делай всё по очереди"): one confirmed-negative
  (CONTINUOUS_FOLD_VS_BET_SIZE), one confirmed-negative
  (CONFIDENCE_GATED_ARCHETYPE_READ), two genuinely-untestable-by-self-
  play (MULTIWAY_TIGHTEN_VS_SHORT_STACK_BEHIND, REAL_RANGE_NUT_
  ADVANTAGE_SIZING). No flag shipped True, but all four ideas were
  taken to clear, honest, well-understood conclusions rather than left
  as vague brainstorm items.

  2026-08-22, Tier 1.5 finally resolved (scripts/tier1_5_bigger_
  sample.sh, up to 1M-hand budget, target_ci=0.5): the "inconclusive_
  small_effect" verdicts RIVER_OVERBET_NUTS_VS_LOOSE and TURN_OVERBET_
  NUTS_VS_LOOSE landed at post-restructure re-check on 2026-08-21 turned
  out to be UNDERPOWERED, not a real shrink -- a much bigger sample
  resolved both CLEANLY confirmed_positive on both seeds:
  RIVER_OVERBET_NUTS_VS_LOOSE +1.11+/-0.54 (seed42, 322k hands) /
  +0.82+/-0.41 (seed777, 338k hands); TURN_OVERBET_NUTS_VS_LOOSE
  +1.45+/-0.71 (seed42, 20k hands) / +1.21+/-0.56 (seed777, 14k hands) --
  magnitudes back in line with the original pre-restructure numbers.
  Both flags' own comments updated with the final result. This closes
  the last open item from this session's full backlog audit -- every
  flag/idea flagged as pending across Tiers 1 through 6 has now reached
  a real, tested, documented conclusion.

Full rule set (every decision point, quoted plainly so it can be read as a
strategy card, not just inferred from code):

  PREFLOP, unopened:
    - BB, action folds/limps to you: check (free).
    - SB specifically (SB_BIGGER_OPEN_SIZING, untested, 2026-08-17): open to
      3bb instead of the flat 2.5bb everywhere else, but ONLY the genuine
      blind-vs-blind case (folds to SB, zero limpers) -- published theory
      says the bigger price denies BB's positional/pot-odds edge of closing
      the action for only 0.5bb more.
    - Otherwise: raise to 2.5bb with a hand in your position's OPEN range
      (UTG 13.9% / MP 16.5% / CO 21.6% / BTN 26.6% / SB 24.5%, by VPIP-implied
      percentile -- the technique from the guide -- UNION real-showdown-data
      additions, see REAL_DATA_RANGE_ADDITIONS and the v7 note above), OR
      (v29, ISO_WIDER_RANGE_OVER_LIMPERS, doubly confirmed positive
      2026-08-12/13, shipped True) the same widened range STEAL_WIDER_VS_NIT
      uses if at least one player has already limped in -- a limper has
      shown a weak/speculative hand, isolate them wider, not just for more
      money. The old bigger-over-limpers sizing rule (ISO_RAISE_OVER_LIMPERS)
      is currently disabled by the 2026-08-12 full-model ablation result. A
      separate v31 candidate can instead isolate limpers tighter but much
      bigger.
      Else fold.

  PREFLOP, facing a raise (any number of raises deep):
    - {AA, KK, QQ, AKs, AKo}: raise (value) to 3x the previous bet if this is
      the first raise faced, or just call that same set if already 3-bet or
      deeper (going a 5th/6th bet deep on a static hand-strength bot isn't
      worth the added complexity) -- EXCEPT (r18v, SHOVE_AA_KK_VS_3BET_PLUS,
      confirmed True, widened to {AA,KK,QQ,AKs,AKo}): this whole set shoves
      all-in instead of calling when already facing a 3-bet+. (sized-4bet-
      instead-of-shove, SIZED_4BET_INSTEAD_OF_SHOVE, untested, 2026-08-17):
      an alternative to the shove above -- 4-bet to ~2.3x (in position) or
      ~2.6x (out of position) the 3-bet instead of shoving all-in, matching
      published 100bb-effective 4-bet sizing theory rather than jamming;
      and EXCEPT (v26, FOLD_PREMIUM_VS_EXTREME_AGGRO, untested, and now also
      structurally dead while the shove range above covers the same hands
      first): facing 2+ raises, if the current to_call is already >=50% of
      hero's remaining stack AND the raiser is a known Nit/TAG, fold
      QQ/AKs/AKo (never AA/KK -- see NEVER_FOLD_PREFLOP).
    - Else, if facing exactly one raise AND the raiser is in
      BLUFF_3BET_TARGET_ARCHETYPES (currently Nit/TAG/LAG, split from the
      donk-bluff target set so LAG can be tested independently here)
      AND your hand is in BLUFF_3BET_RANGE (v24, BLUFF_3BET_VS_TIGHT):
      bluff-raise (3-bet) instead of just calling; confirmed +1.80 bb/100
      at 2M hands/arm.
    - Else, if hero is in SB facing exactly one raise from a late-position
      steal seat (SB_THREEBET_OR_FOLD_VS_STEAL, untested, 2026-08-17):
      3-bet the whole range that would otherwise call (call_ranges["SB"] |
      VALUE_3BET), or fold -- no flat call. Published SB-specific theory:
      SB is worse-positioned than any other cold-caller (acts first every
      remaining street against a raiser who now also has position), so
      3-betting to win preflop or play a bigger pot with initiative beats
      calling into a tough OOP spot.
    - Else, if facing exactly one raise: call with a hand in your position's
      CALL range (half the open VPIP, e.g. UTG ~7% / BTN ~13.3% -- the
      tighter, stronger half of what you'd open) -- (v30, SIZE_SCALED_
      CALL_RANGE, untested) widened by 30% VPIP if the raise-to is <=2bb
      (a cheap price), or narrowed by 30% VPIP if it's >=4bb (a worse
      price, usually a stronger range behind it), instead of one fixed
      range regardless of how big the actual raise was.
    - Else: fold.

  POSTFLOP, checked to (to_call <= 0), any street:
    - Bet 50% pot if your hand is top-pair-or-better (value bet) --
      regardless of whether you had preflop initiative. Sizing tiers on
      top of that base, each independently untested: (v28, OPTIMAL_VALUE_
      SIZING_PER_ARCHETYPE) a real EV comparison between the standard and
      big sizing for whatever archetype is actually known, using that
      archetype's own real fold rate at each size -- overrides A2's
      Nit/TAG-only shortcut when it fires; (v27, RIVER_OVERBET_NUTS_VS_
      LOOSE) a genuine overbet (150% pot) on the river specifically with
      a near-nut hand (trips+) against a known loose/weak archetype.
    - Flop ONLY, additionally: bet 50% pot with ANY hand if you had preflop
      initiative and haven't bet yet this street (the one Tier-1 fold-equity
      cbet -- confirmed by A/B test to be worth keeping).
    - Turn/river ONLY, additionally (v25, BARREL_BLUFF_VS_TIGHT, untested):
      bet with no hand at all if you had preflop initiative, haven't bet
      yet this street, a real scare card just arrived (a fresh overcard or
      a new flush possibility -- see _is_scare_card), and the single live
      opponent is a known Nit/TAG/LAG.
    - Turn ONLY, additionally (float-flop-in-position's follow-up,
      FLOAT_FLOP_IN_POSITION, confirmed positive both seeds, 2026-08-17):
      bet 66% pot with no hand if you called a bet on the flop this hand
      and got checked to -- the float's follow-through, independent of
      whether you had preflop initiative (a float is a positional line,
      not a range-based one).
    - River ONLY, additionally (RIVER_BLUFF_MISSED_DRAW, confirmed positive
      both seeds, 2026-08-17): bet 66% pot with no hand if you personally
      held a real flush/straight draw on the turn that missed by the river,
      against a known tight archetype (see _had_missed_draw) -- a credible
      "drew and missed, keep firing" bluff, distinct from BARREL_BLUFF_VS_
      TIGHT's scare-card trigger above (this one doesn't need a scare card,
      just hero's own missed draw).
    - Otherwise: check. "Don't auto-barrel" means don't fire without a hand
      on the turn/river -- it does not mean never bet a strong hand.

  POSTFLOP, facing a bet, any street:
    - Call with top-pair-or-better (rank-count based -- see
      has_top_pair_or_better -- now including made straights/flushes). v22
      tested raising instead with two-pair-or-better (VALUE_RAISE_FACING_
      BET, has_very_strong_hand) -- measured WORSE (-9.66 bb/100, see the
      constant's comment above), shipped OFF; call-only stays the live
      default even for a flopped set. Tested and rejected (both shipped
      OFF, confirmed negative both seeds, 2026-08-17): FOLD_MARGINAL_VS_
      CHECK_RAISE (fold a plain top-pair hand to a genuine check-raise,
      heads-up, non-loose aggressor); FOLD_MARGINAL_VS_BIG_DONK (fold a
      plain top-pair hand to a BIG, >=66% pot, donk lead specifically while
      hero has preflop initiative); FOLD_TOP_PAIR_VS_WET_BOARD_TIGHT (fold
      a plain top-pair hand to a real-sized bet on a wet board from a known
      tight archetype). All three are standard published micro-stakes
      folding advice that does not transfer to this specific ML-bot
      population -- see the changelog above for numbers.
    - Else, IF the specific opponent who bet is a known Loose-passive/
      Station/Maniac (see LOOSE_ARCHETYPES): call with ANY pair or better
      (has_any_pair_or_better) instead of the stricter top-pair bar. This is
      the bot's one deliberate piece of opponent modeling -- see the v10 note
      above for why it's worth so much more than everything else combined.
    - Else call with a real flush or open-ended-straight-ish draw IF the
      price is at least as good as the draw's rough continue-equity
      (~35% w/ two cards to come on the flop, ~19% w/ one card on the turn --
      see should_call_with_draw). Never on the river (no card left to come).
    - Else, flop only (float-flop-in-position, FLOAT_FLOP_IN_POSITION,
      untested, 2026-08-17): call anyway with no hand and no draw IF hero is
      in position against the single live opponent and that opponent isn't a
      known loose archetype -- the published "float" line, planning to bet
      the turn if checked to again (see the checked-to section's turn-bet
      list below) rather than giving up the pot immediately.
    - Else fold.

  Known, disclosed simplifications (not bugs, just where "simple" stops):
    - Hand-strength/draw detection is rank-count and rank-window based, no
      full 7-card evaluator -- doesn't distinguish open-ended draws from
      gutshots, doesn't handle backdoor draws, doesn't read board texture
      beyond what's needed for these two checks.
    - Bet sizing is always 50% pot / a single fixed preflop size -- no
      sizing-for-effect, no polarization, no adjusting for stack depth.
    - Opponent modeling is limited to the one postflop-calling-bar rule
      above -- ranges, sizing, and the flop cbet stay identical regardless
      of archetype, unlike the live practice app's
      dossier-aware EV panel.
"""

import sys
import zlib
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
sys.path.insert(0, str(ANALYSIS_ROOT))

from src.analysis.hand_rankings import RANKS, compute_hand_rankings
from src.analysis.implied_range import implied_range
from src.engine.range_equity import _expand_range, combos_vs_range_equity_on_board, filter_combos_for_board
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
# 2026-08-12: original thresholds (2.0 / 4.0) were textbook picks, not
# checked against this population's actual sizing -- confirmed DEAD:
# scripts/probe_chance_enumeration.py's r30 ablation test found ZERO
# divergent hands over 50k, and a direct measurement of what hero actually
# faces (949 "facing exactly one raise" preflop spots, 15k-hand sample)
# showed the ML bots' open sizing is nearly bimodal-deterministic, not a
# spread: p10 through p90 all sit at exactly 2.35bb, then a small tail
# jumps straight to 3.25bb (p95/p99) -- NOTHING ever lands at <=2.0 or
# >=4.0, so SIZE_SCALED_CALL_RANGE could never do anything against this
# specific opponent pool regardless of sample size. Recalibrated to
# bracket the two real observed clusters instead of a theoretical
# min-raise/big-raise split -- re-test pending with these values.
SMALL_RAISE_BB_THRESHOLD = 2.5  # raise-to at or below this many bb -- wider call range (catches the ~2.35bb cluster)
BIG_RAISE_BB_THRESHOLD = 3.0  # raise-to at or above this many bb -- narrower call range (catches the ~3.25bb cluster)
CALL_VPIP_WIDE_MULTIPLIER = 1.3
CALL_VPIP_NARROW_MULTIPLIER = 0.7

# Candidate: make cold-call ranges depend on the raiser's position, not only
# hero's seat. An UTG/MP open represents a stronger range than a CO/BTN/SB
# steal, so the same hero hand should not be treated identically in both spots.
CALL_RANGE_BY_RAISER_POSITION = False  # r17v (2026-08-13): tested, not demonstrated -- +0.07+/-0.99 bb/100 @ seed42, -0.98+/-0.99 @ seed777 (both inconclusive_small_effect, combined-CI 1.40 vs 1.05 delta, consistent with true-zero). Kept off.
EARLY_RAISER_POSITIONS = {"UTG", "MP"}
LATE_STEAL_RAISER_POSITIONS = {"CO", "BTN", "SB"}

# r27 (2026-08-13, untested): explicit implied-odds/set-mining rule (the
# published "15/25/35" rule of thumb), a genuinely different mechanism from
# the fixed VPIP call range above -- it's gated on effective STACK DEPTH
# relative to the call amount, not hand-strength percentile. A small pocket
# pair or suited connector outside the normal call range can still be a
# profitable cold-call if there's enough money behind to get paid when it
# hits (set-mining a pair needs ~15x the call in implied odds, a suited
# connector needs ~25x -- the "35x" tier is for weaker speculative hands
# this bot doesn't otherwise consider calling with, so it's omitted here).
# Only extends the call decision to hands NOT already in the fixed call
# range; never narrows it.
SET_MINE_IMPLIED_ODDS = True
SET_MINE_POCKET_PAIRS = {"22", "33", "44", "55", "66", "77", "88", "99"}
SET_MINE_SUITED_CONNECTORS = {"54s", "65s", "76s", "87s", "98s", "T9s", "JTs"}
SET_MINE_PAIR_IMPLIED_ODDS_MULTIPLE = 15.0
SET_MINE_CONNECTOR_IMPLIED_ODDS_MULTIPLE = 25.0

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

# 2026-08-17 (user-prompted research check): this file has never had ANY
# SB-specific logic -- OPEN_VPIP_BY_POSITION/etc. treat SB as just another
# position slot in the same generic dicts. Published small-blind-specific
# strategy (Upswing "Small Blind Strategy Tips" et al.) makes two concrete,
# testable claims that don't apply to any other position:
#   1. Open bigger (~3bb, not the flat 2.5bb everywhere else) specifically in
#      the blind-vs-blind case (folds to SB, only BB left) -- a bigger price
#      denies BB's positional/pot-odds advantage of closing the action last
#      with only 0.5bb more to call. Only fires with zero limpers already in
#      (limped-pot isolation already has its own, bigger sizing above).
SB_BIGGER_OPEN_SIZING = False
SB_OPEN_SIZING_BB = 3.0
# 2026-08-17, follow-up: also tested 3.5bb specifically (sb-open-3.5bb
# preset), in case the original 3.0bb step (inconclusive, +0.19/+0.04) was
# just too small to move the needle -- still inconclusive both seeds,
# +0.27+/-0.15 (seed42) / +0.08+/-0.10 (seed777), even tighter around zero
# than the 3.0bb result. Confirms this isn't a step-size artifact: SB open
# sizing genuinely doesn't matter for this population in the blind-vs-
# blind case. Stays False.
#   2. "3-bet with your entire continue range" facing a late-position
#      (CO/BTN) steal raise, instead of ever flat-calling -- SB is worse
#      positioned than any other cold-caller (acts first EVERY street,
#      against a raiser who now also has position for the rest of the hand),
#      so the theory says fold equity + range protection from 3-betting beats
#      just calling and playing a tough OOP pot. Reuses the existing call
#      range as the "entire continue range" (call_ranges["SB"] | VALUE_3BET)
#      rather than inventing a new hand list from scratch.
SB_THREEBET_OR_FOLD_VS_STEAL = True

# 2026-08-17, diagnostic-only, never meant to ship: SB_THREEBET_OR_FOLD_VS_
# STEAL confirmed 3-bet beats flat-call, but that doesn't establish that
# flat-calling itself is +EV -- it could be that this bot's postflop game
# is weak enough OOP that no continue is profitable there, and 3-betting
# only wins because it more often ends the hand outright. This flag answers
# a different, narrower question: is SB's flat-call range positive EV
# against a steal AT ALL, compared to simply folding it (not compared to
# 3-betting). Only meaningful with SB_THREEBET_OR_FOLD_VS_STEAL off (that
# flag already intercepts and returns before this point when on) -- the
# test harness enforces that by construction (see probe_chance_
# enumeration.py's "sb-flat-call-vs-fold-diagnostic" special-cased
# comparison, which forces both off/on arms with SB_THREEBET_OR_FOLD_VS_
# STEAL=False so only this flag varies).
SB_FOLD_VS_STEAL_DIAGNOSTIC = False
# RESULT (2026-08-17): confirmed NEGATIVE both seeds, -9.58+/-4.37
# (seed42) / -4.82+/-2.53 (seed777) -- i.e. folding SB's call range
# measures WORSE than flat-calling it, clearly and on both seeds. Answers
# the diagnostic question directly: SB's flat-call range vs a steal is
# solidly +EV in absolute terms, not just "less bad than folding." The
# concern that SB_THREEBET_OR_FOLD_VS_STEAL's win was masking a weak OOP
# postflop game is NOT supported by this result -- calling is a genuinely
# profitable action on its own; 3-betting is simply even better than an
# already-profitable call, not a rescue from an unprofitable one. Stays
# False (diagnostic-only, was never meant to ship either way).

# r28 (2026-08-13, untested): rake-adjusted early-position open sizing.
# Published low-stakes/high-rake advice: a smaller open (down to ~2.2bb from
# UTG/MP) offers a cheaper price to steal blinds or get heads-up in position
# while hedging against 3-bets/cold-calls, since "no flop no drop" rake
# structures (this sim's RAKE_PERCENT/RAKE_CAP_BB) mean pots that die
# preflop pay no rake at all -- makes ending the pot preflop relatively more
# attractive than the flat 2.5bb-everywhere policy above. Untested here;
# only applies to UTG/MP if the flag fires (CO/BTN/SB already open wider,
# not smaller, per the same sources).
RAKE_ADJUSTED_OPEN_SIZING = False
RAKE_ADJUSTED_OPEN_SIZING_BB = 2.2
RAKE_ADJUSTED_OPEN_POSITIONS = {"UTG", "MP"}

# r22 (2026-08-13, untested): position-dependent 3-bet sizing instead of one
# flat multiplier. Published theory: ~3-3.5x in position (deeper post-flop
# play available, less reliant on folds), ~4-4.5x out of position (harder to
# realize equity post-flop, so the 3-bet leans more on fold equity and wants
# a bigger price). Applied via _threebet_multiplier(hand, seat, raiser_seat)
# below wherever THREEBET_MULTIPLIER is currently used directly (value
# 3-bet, bluff 3-bet, squeeze).
THREEBET_SIZE_BY_POSITION = True
THREEBET_MULTIPLIER_IP = 3.0
THREEBET_MULTIPLIER_OOP = 4.0


def _threebet_multiplier(hand: Hand, seat: int) -> float:
    if not THREEBET_SIZE_BY_POSITION:
        return THREEBET_MULTIPLIER
    raiser_seat = _last_preflop_raiser_seat(hand)
    if raiser_seat is None:
        return THREEBET_MULTIPLIER
    if _is_hero_in_position_vs_raiser(hand, seat, raiser_seat):
        return THREEBET_MULTIPLIER_IP
    return THREEBET_MULTIPLIER_OOP

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
# 2026-08-17: user directive -- was 0.525 ("~55%" in the docstring's plain-
# language strategy card above was always describing this same constant,
# both the value-bet base size AND the Tier-1 unconditional flop c-bet reuse
# it, so one change covers both). Changed to a flat 50% pot, a more standard
# round number; not itself an A/B-tested hypothesis, a direct instruction.
STANDARD_SIZING_POT_FRACTION = 0.50

# v27: see the RIVER_OVERBET_NUTS_VS_LOOSE comment in choose_abc_action's
# checked-to branch. A genuine overbet (>100% pot) -- BIG_VALUE_SIZING_
# POT_FRACTION's 0.75 never crosses the pot itself.
RIVER_OVERBET_NUTS_VS_LOOSE = True  # confirmed positive both seeds at bigger sample 2026-08-16, see changelog. 2026-08-21 post-restructure re-check (bigger N, up to 144k hands): direction still positive both seeds but shrunk close to zero, both inconclusive_small_effect -- turned out to just be underpowered, not a real shrink: 2026-08-22 re-check with a much bigger budget (up to 338k hands, target_ci=0.5) resolved CLEANLY confirmed_positive both seeds, +1.11+/-0.54 (seed42) / +0.82+/-0.41 (seed777) -- back in line with the original pre-restructure magnitude. Tier 1.5 backlog item closed.
RIVER_OVERBET_POT_FRACTION = 1.5  # standard-theory "genuine overbet" size, not fit to a measured breakeven point

# 2026-08-18 (untested): turn analogue of RIVER_OVERBET_NUTS_VS_LOOSE --
# generalizes the same "genuine overbet with a real near-nut hand against a
# known loose/weak archetype" idea to the turn instead of restricting it to
# the river. Published theory: overbetting for value against stations/
# loose-passive players is a general polarization tool that works
# especially well the moment hero holds a clear range/nut advantage with
# betting already shown on an earlier street, not something specific to
# there being no more cards to come -- the river-only restriction was
# never itself a tested finding, just where the idea was first tried.
# Same has_trips_or_better bar and LOOSE_ARCHETYPES target as the river
# version; own flag/sizing constant so the two can be tuned independently
# (a turn overbet carries extra risk from redraws the river version
# doesn't, so it isn't assumed to share the exact same optimal sizing).
TURN_OVERBET_NUTS_VS_LOOSE = True  # 2026-08-18: confirmed POSITIVE both seeds, +1.86+/-0.84 (seed42, 10k hands) / +1.69+/-0.81 (seed777, 16k hands) -- consistent magnitude, resolved fast. Shipped True. 2026-08-21 post-restructure re-check (bigger N, 8k hands both seeds): direction still positive both seeds but shrunk close to zero, both inconclusive_small_effect -- same underpowered-not-shrunk pattern as RIVER_OVERBET_NUTS_VS_LOOSE. 2026-08-22 re-check with a bigger budget resolved CLEANLY confirmed_positive both seeds, +1.45+/-0.71 (seed42, 20k hands) / +1.21+/-0.56 (seed777, 14k hands). Tier 1.5 backlog item closed.
TURN_OVERBET_POT_FRACTION = 1.5

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
OPTIMAL_VALUE_SIZING_PER_ARCHETYPE = True  # 2026-08-12/13: confirmed positive across 4 independent chance-enumeration samples, all positive direction (+2.25, +0.82, +4.88, and a precise large-sample +1.45+/-0.62 @ 54k hands/2001 divergent -- the last one clears the standard confirmed_positive bar cleanly). Shipped True. 2026-08-21: magnitude pinned down with a much bigger single run (90k hands, 3035 divergent, target_ci=0.5), +1.39+/-0.79 bb/100 -- right in the middle of the prior 0.68-4.88 range, resolves the Tier-3 backlog item.
ASSUMED_VALUE_HAND_EQUITY = 0.75  # disclosed, single-number approximation of "how often a should_bet hand is still best when called" -- not a real per-hand equity computation

# monster-pot fix, hero side -- see choose_abc_action's
# HERO_PROGRESSIVE_POT_DAMPING comment. Same shape/rationale as behavior_
# clone.py's PROGRESSIVE_POT_DAMPING, applied to hero's own value-bet sizing.
# 2026-08-12 full-model ablation measured this as harmful:
# without_rule - full_model = +72.06 +/- 6.94 bb/100, so ship it off.
HERO_PROGRESSIVE_POT_DAMPING = False
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
SIZE_UP_ON_TURN = False  # full-model ablation: +0.46 +/- 0.59, no proven benefit

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
SIZE_UP_WITH_VERY_STRONG_HAND = True  # bet BIG_VALUE_SIZING_POT_FRACTION instead of standard with two-pair-or-better (has_very_strong_hand)
SIZE_UP_ON_WET_BOARD = True  # bet BIG_VALUE_SIZING_POT_FRACTION instead of standard on a two-tone/monotone/well-connected board

# 2026-08-18: the flip side of SIZE_UP_ON_WET_BOARD, flagged as a separate
# untested question at the time that one shipped -- see the use site's
# comment in choose_abc_action for the full disclosure (only touches the
# three "plain" bluff triggers without their own dedicated sizing).
SMALLER_BLUFF_ON_WET_BOARD = False  # 2026-08-18: confirmed NEGATIVE both seeds, -4.07+/-3.72 (seed42, 8k hands) / -4.46+/-3.78 (seed777, 10k hands). Stays False.
WET_BOARD_BLUFF_POT_FRACTION = 0.33  # standard-theory "block/probe-sized bluff" number, not fit to a measured breakeven point

# v16, C1: the bot currently treats "someone already limped" identically to
# "unopened pot" -- always OPEN_SIZING_BB flat. Standard live convention is
# to isolate a limper for MORE than a plain open (open size + ~1bb per
# limper), both to charge the limper for their speculative hand and to price
# out anyone left to act. This is a standard-theory sizing convention, not a
# number fit to a specific measured breakeven point (unlike A2/B2's
# archetype-table-derived sizes) -- flagged as such.
ISO_RAISE_OVER_LIMPERS = False  # full-model ablation: -0.60 +/- 0.99, no proven benefit
ISO_SIZING_PER_LIMPER_BB = 1.0

# v31: anti-multiway limper isolation candidate. This is deliberately NOT the
# old C1 rule: it narrows the range and uses a much bigger raise so callers
# behind hero get a worse price and hero more often plays heads-up.
TIGHT_BIG_ISO_RAISE_LIMPERS = True
TIGHT_ISO_VPIP_MULTIPLIER = 0.85
TIGHT_ISO_BASE_SIZING_BB = 5.5
TIGHT_ISO_SIZING_PER_LIMPER_BB = 1.5
# 2026-08-13: the strategy card describes this as "70/85% of the normal open
# VPIP" and "normal open range" is itself defined elsewhere as the synthetic
# VPIP range UNION REAL_DATA_RANGE_ADDITIONS (the real-showdown-data floor) --
# but _tight_iso_range_cache below never actually unions that floor set,
# unlike _open_range_cache and _steal_range_cache which both do. Never tested
# with it included. Same class of gap as the SIZE_SCALED_CALL_RANGE narrow-
# tier bug found earlier tonight (a precomputed alternate tier silently
# missing a union the "parent" range includes) -- off by default here since,
# unlike that case, this flag is untested and TIGHT_BIG_ISO_RAISE_LIMPERS is
# a currently-shipped True rule, so the standing policy is test first.
TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR = True

# 2026-08-17, follow-up round (user's idea, untested): also narrow the
# RANGE for each limper beyond the first, not just the sizing -- the
# mechanism above only scales TIGHT_ISO_BASE_SIZING_BB/_PER_LIMPER_BB with
# n_limpers; the range itself (TIGHT_ISO_VPIP_MULTIPLIER) is identical
# whether there's 1 limper or 3. Standard live-poker isolation logic: more
# limpers means isolating profitably to actually go heads-up is harder
# (any of them could still call/squeeze behind), and a bigger potential
# multiway pot wants more raw hand strength, not just a bigger price. Not
# fit to a measured breakeven point -- testing the idea, not a derived
# number.
TIGHT_ISO_TIGHTENS_PER_EXTRA_LIMPER = False
TIGHT_ISO_EXTRA_LIMPER_STEP = 0.85  # each limper beyond the first multiplies the effective VPIP multiplier by this again, compounding with TIGHT_ISO_VPIP_MULTIPLIER
# RESULT (2026-08-17): confirmed NEGATIVE both seeds, -5.98+/-3.29
# (seed42) / -14.42+/-6.09 (seed777). Narrowing the range further per
# extra limper measures worse than leaving it fixed (today's default:
# only sizing scales with n_limpers, the range stays constant). Plausible
# reading: the fixed fake-tight range is already tight enough that
# further narrowing mostly cuts hands that were still fine to isolate
# with, while the bigger sizing already does the real work of making
# overcalls unattractive -- same "range-narrowing tweaks tend to lose to
# this population" pattern as several other rejected ideas in this file.
# Stays False.

# r26 (2026-08-13, untested): limp-reraise trap. Published theory: limping
# the very top of hero's range (AA/KK) from an UNOPENED pot instead of
# raising, then re-raising if someone behind raises over the limp, extracts
# more money than a standard open against opponents who over-attack limpers
# -- but it's a transparent, low-frequency play (real sources note it's
# "rarely used by good players" and mostly seen at small stakes), and more
# viable the deeper the effective stacks (100bb+; this sim runs right at
# 100bb, the low end of where sources say it's still worth it). Applied with
# a fixed frequency (not every time, or the limp itself becomes a tell) via
# a per-hand deterministic hash rather than hero's hole cards, so the same
# AA doesn't always limp or always raise. If no one raises behind the limp,
# hero just open-limped a premium hand for that orbit -- no reraise trap
# fires, same downside real players accept with this play.
LIMP_TRAP_WITH_MONSTERS = False
LIMP_TRAP_HAND_SET = {"AA", "KK"}
LIMP_TRAP_FREQUENCY = 0.3  # limp (instead of raise) this fraction of the time with a LIMP_TRAP_HAND_SET hand

# Limp behind instead of iso/fold with hands that play well multiway and are
# too weak for the tight-big-iso range.
LIMP_BEHIND_OVER_LIMPERS = True
LIMP_BEHIND_VPIP_MULTIPLIER = 0.55
LIMP_BEHIND_EXTRA_HANDS = {
    "22", "33", "44", "55", "66",
    "54s", "65s", "76s", "87s", "98s", "T9s",
    "A2s", "A3s", "A4s", "A5s",
}

# 2026-08-12: r16v A/B tested three LIMP_BEHIND_VPIP_MULTIPLIER tiers
# (0.45/0.55/0.75, i.e. narrow/standard/wide -- see scripts/probe_chance_
# enumeration.py's r16v-limp-behind-* presets) against baseline. All three
# measured the SAME confirmed-positive effect: +10.3 to +10.5 bb/100
# across two independent seeds and sample sizes (6k and 20k hands) --
# looked like a caching bug at first, but direct instrumentation proved
# otherwise: of every divergent hand found, 100% came from the FIXED
# LIMP_BEHIND_EXTRA_HANDS set above, ZERO from the swept VPIP-multiplier-
# scaled portion of the range. Real, well-evidenced conclusion: against
# this population's actual self-play dynamics, the multiplier parameter
# has NO measurable effect -- the entire benefit comes from the fixed
# small-pairs/suited-connectors/small-suited-aces core, not from how much
# wider or narrower the swept tier is around it. The multiplier value doesn't
# matter for THIS population; don't spend more time tuning it without first
# checking whether the swept region is ever actually reached (the same
# class of dead-parameter
# bug found and fixed for v30/r19v-tight this same night, just resolved
# here as "confirmed genuinely inert" instead of "off by a factor").
# 2026-08-16: the confirmed-positive result above was never actually shipped
# at the time -- found and fixed during a full re-audit of every remaining
# untested/unshipped flag. Shipped True now; nothing else about the rule
# changed.

# v29: see the ISO_WIDER_RANGE_OVER_LIMPERS comment at its use site above
# (n_raises==0 branch). Standard live-poker convention (isolate limpers
# wider, not just bigger) -- not fit to a measured breakeven point, same
# disclosure as C1 itself.
#
# 2026-08-12/13: doubly confirmed positive in ISOLATION via chance-
# enumeration probe, two independent seeds/samples (+22.10+/-5.18 @
# seed42, +19.67+/-6.04 @ seed777) -- real at the time it was measured.
#
# 2026-08-17 CORRECTION, found while explaining this code to the user:
# TIGHT_BIG_ISO_RAISE_LIMPERS (v31, added the same day, also True) is
# unconditional on n_limpers>=1 with no hand-set gate, so it always wins
# in choose_abc_action's `use_tight_big_iso`/`use_iso_wide` branch --
# this flag's own branch has been STRUCTURALLY DEAD CODE (unreachable)
# ever since v31 shipped, same class of situation as SHOVE_AA_KK_VS_
# 3BET_PLUS making FOLD_PREMIUM_VS_EXTREME_AGGRO unreachable, just never
# caught/documented for this pair until now. The +22.10/+19.67 numbers
# above describe this rule tested ALONE against a baseline with no
# isolation-range change at all -- they say nothing about how it compares
# to TIGHT_BIG_ISO_RAISE_LIMPERS specifically, which is what actually
# governs live behavior.
# Ran the real head-to-head (tight-iso-vs-wide-iso-headtohead preset):
# baseline = today's actual default (both flags True, TIGHT_BIG_ISO wins
# in practice), treatment = this flag live instead (TIGHT_BIG_ISO_RAISE_
# LIMPERS=False, ISO_WIDER_RANGE_OVER_LIMPERS=True) -- confirmed NEGATIVE
# both seeds, -14.19+/-11.63 (seed42) / -33.94+/-17.01 (seed777). Today's
# default (TIGHT_BIG_ISO_RAISE_LIMPERS, narrower range + much bigger
# sizing) is genuinely better than this rule, not just winning by code
# priority accident. Flipped to False -- no behavior change (it was
# already unreachable while TIGHT_BIG_ISO_RAISE_LIMPERS stayed True), but
# now the flag's own value honestly reflects "tested worse, not shipped"
# instead of falsely reading as "shipped True, strong lever."
ISO_WIDER_RANGE_OVER_LIMPERS = False

# v19: open bigger with a premium hand (reuses VALUE_3BET_TIGHT below as the
# "premium" set), stacking with the C1 per-limper bonus above -- i.e. a
# premium hand opened over 2 limpers gets BOTH bonuses. User's hypothesis,
# untested until now; note this cuts against the usual "keep your whole
# range's sizing the same so it isn't readable" argument, worth checking
# empirically rather than assuming either way given how this file's other
# theory-first guesses (A1/A2/B1/B2) mostly measured as noise.
SIZE_UP_PREMIUM_OPENS = True  # 2026-08-13: v19b's old whole-game test (+1.76/-0.76, inside CI, sign flip) was too imprecise. Re-tested with the chance-enumeration probe (r20): +4.00+/-1.89 @ seed42, +3.05+/-1.44 @ seed777, combined-CI-in-quadrature 2.38 vs a 0.95 delta between them -- well inside, confirmed. Shipped True.
PREMIUM_OPEN_SIZING_BONUS_BB = 1.5

# 2026-08-20 (untested): SIZE_UP_PREMIUM_OPENS generalized one decision
# point later -- the same idea (a stronger-than-baseline hand sizes up
# instead of keeping the range's sizing flat) applied to the VALUE 3-bet
# (facing exactly one raise, notation in value_3bet_range) instead of the
# open-raise. Reuses VALUE_3BET_TIGHT as the "premium" subset, same
# pattern SIZE_UP_PREMIUM_OPENS already established rather than defining a
# third similar-but-different premium-hand list. Needs its own A/B
# confirmation before shipping True.
SIZE_UP_PREMIUM_3BETS = False  # 2026-08-21: tested (scripts/tier5_confirm.sh, size-up-premium-3bets, --comparison current --adaptive) -- confirmed NEGATIVE seed42 (-1.80+/-1.63), inconclusive-but-negative-leaning seed777 (-0.50+/-0.98, crosses zero). Unlike SIZE_UP_PREMIUM_OPENS, sizing up a value 3-bet specifically with a premium hand does NOT help -- likely because a 3-bet already telegraphs strength, so the extra size just makes it easier for the rest of the raiser's continuing range to fold profitably against, losing value rather than gaining it. Stays False, tested-and-rejected (not "untested").
PREMIUM_3BET_SIZING_BONUS_BB = 1.5

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
BARREL_BLUFF_VS_TIGHT = True  # 2026-08-12/13: doubly confirmed positive via chance-enumeration probe, two independent seeds (+1.99+/-0.99 @ seed42, +1.33+/-0.65 @ seed777, both individually confirmed_positive, cross-check consistent). Shipped True.

VALUE_3BET_TIGHT = {"AA", "KK", "QQ", "AKs", "AKo"}
VALUE_3BET_WIDE = VALUE_3BET_TIGHT | {"JJ", "TT", "AQs", "AQo"}
# A/B-test switch: Tier 2 found this population barely 3-bets (2-5% of raise
# responses) and probably under-punishes it -- flagged there as an unproven
# hypothesis, not a validated finding. Widening the value-3-bet range adds
# preflop-only fold equity, which is specifically valuable against rake
# ("no flop no drop" -- a preflop-only win pays zero rake).
USE_WIDE_VALUE_3BET = True  # 2026-08-13/2026-08-21: v9's old whole-game test (+0.80 @500k, inside CI) was too imprecise -- last remaining Tier-1 "old method only" backlog item, re-tested with the modern chance-enumeration method 2026-08-21: confirmed POSITIVE both seeds, +6.73+/-2.88 (seed42) / +3.60+/-1.78 (seed777). Resolves the backlog item, no longer pending.
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
FOLDABLE_PREMIUM_VS_EXTREME_AGGRO = {"QQ", "AKs", "AKo"}
EXTREME_AGGRO_STACK_FRACTION = 0.5  # to_call >= this fraction of hero's remaining stack counts as "extreme"
TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD = {"Nit", "TAG"}

# r13 candidate: when the pot is already 3-bet/4-bet, AA/KK have no reason
# to stay passive in this static hand-strength strategy. Test shoving the
# never-fold preflop pair bucket instead of flat-calling and letting worse
# hands realize equity cheaply. QQ/AK stay in the older call/fold branch until
# separately tested.
SHOVE_AA_KK_VS_3BET_PLUS = True
SHOVE_VS_3BET_PLUS_RANGE = {"AA", "KK", "QQ", "AKs", "AKo"}

# 2026-08-17 (r18v2, user-prompted research check): published 4-bet theory
# (Upswing "4-Bet Size Strategy" et al.) is consistent that at 100bb
# effective -- this sim's actual depth -- an all-in 4-bet is NOT standard for
# a static premium-only range; the usual size is ~2.3x the 3-bet in position,
# ~2.5-2.6x out of position (roughly 18-25bb), leaving a real postflop stack
# behind. All-in only becomes the normal 4-bet once effective stacks shrink
# to around 50bb. SHOVE_AA_KK_VS_3BET_PLUS above was confirmed positive
# (+31.41/+15.54 bb/100) against the OLD flat-call baseline, but that A/B
# never asked whether shoving specifically (vs. a smaller sized 4-bet that
# still re-raises) is the best way to capture that edge -- this flag tests
# exactly that question, sized version vs. shove version, both already-
# confirmed-better than calling. Reuses THREEBET_SIZE_BY_POSITION's IP/OOP
# distinction technique (_is_hero_in_position_vs_raiser) rather than
# inventing a second position-detection mechanism.
SIZED_4BET_INSTEAD_OF_SHOVE = False
SIZED_4BET_MULTIPLIER_IP = 2.3
SIZED_4BET_MULTIPLIER_OOP = 2.6

# v15, B1: archetype_vs_raise.csv / archetype_facing_bet.csv show Maniac and
# Station continue/call facing aggression far more than the population
# average -- a thin value 3-bet (not just a premium hand) is more often still
# ahead of what they'd continue with. Widen VALUE_3BET specifically when the
# original raiser hero is facing is a known Maniac/Station. A modest, round
# widening (not fit to a specific breakeven number) -- the hypothesis is
# "wider works here," not a precise optimal range.
LOOSE_ARCHETYPES_FOR_3BET = {"Maniac", "Station"}
VALUE_3BET_VS_LOOSE = VALUE_3BET | {"99", "88", "AJs", "AJo", "KQs", "KQo"}
WIDER_3BET_VS_LOOSE = True  # 2026-08-20: was "active but unconfirmed" (old whole-game method, +1.62 @500k, inside CI) -- re-confirmed POSITIVE both seeds with the modern chance-enumeration method against the new archetype population, +4.91+/-2.43 (seed42) / +5.99+/-2.72 (seed777). See the changelog entry near the end of this docstring.

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
SQUEEZE_WIDER_RANGE = False
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
# demonstrated effect either direction. **THIS RESULT IS NOW KNOWN INVALID**
# (see 2026-08-12 bug below) -- both arms of that A/B test behaved
# identically because the fold condition literally could never fire, so
# "no demonstrated effect" was comparing two copies of the same strategy,
# not a real neutral finding.
#
# 2026-08-12 BUG (fixed in choose_abc_action): the fold condition compared
# to_call against a `pot_before` that already included the opponent's
# current bet -- to_call/pot_before is algebraically bet/(pot_before_bet+
# bet), which can never reach or exceed 1.0 for any finite bet. A
# 300,000-hand probe confirmed exactly zero divergent hands. Fixed by
# comparing against the pot as it stood BEFORE the bet instead.
#
# 2026-08-12 FOLLOW-UP, after the fix: re-tested at 50k hands, STILL zero
# divergent hands -- but this time confirmed as a real structural fact,
# not a bug. Direct instrumentation of 15,000 hands found 44 genuine
# postflop overbet-facing spots, and in ALL 44 hero held zero pair (air).
# Why: this bot always value-bets any made hand the instant it's checked
# to (`should_bet = made or ...` in the to_call<=0 branch above) -- so the
# only version of hero that ever reaches "checked, then faced a bet" on a
# given street is, by the bot's own consistent policy, exactly the
# sub-population that had no hand to bet with in the first place. A
# made-but-not-very-strong hand facing an overbet requires hero to have
# passively checked a real hand, which this bot's architecture doesn't
# allow. FOLD_TOP_PAIR_VS_OVERBET targets a scenario this bot's own other
# rules make nearly unreachable -- not a promising avenue to keep
# revisiting without first relaxing the "always bet a made hand" rule
# itself (untested, bigger change, not attempted).
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
# RESULT, this specific implementation: eventually cleared the bar at real
# power. scripts/simulate_abc_bot.py --bluff-3bet, real rake, ground-truth
# archetypes, same seed:
#   80k hands/arm:  baseline +57.90 (CI +/-3.92) vs v24 +62.19 (CI +/-3.96),
#                   delta +4.29 -- leaning positive, inside the ~5.6 combined
#                   noise band.
#   300k hands/arm: baseline +57.12 (CI +/-2.03) vs v24 +59.67 (CI +/-2.04),
#                   delta +2.56 -- STILL inside the ~2.9 combined noise band
#                   (barely).
#   2M hands/arm:   baseline +57.89 (CI +/-0.78) vs v24 +59.70 (CI +/-0.79),
#                   delta +1.80, clearing the ~1.11 combined CI.
BLUFF_3BET_VS_TIGHT = True
BLUFF_3BET_TARGET_ARCHETYPES = {"Nit", "TAG", "LAG"}
BLUFF_3BET_RANGE = {"A9o", "A8o", "A5s", "A4s", "KQo", "KJs", "QJs", "JTs", "T9s", "98s"}

# r25 (2026-08-13, untested): alternate bluff-3bet hand selection built
# purely from blocker theory instead of BLUFF_3BET_RANGE's playability-based
# picks. Published theory: the best 4/5-bet-bluff-style hands are suited
# wheel aces (A5s-A2s) because holding an ace removes AA/AKs/AKo combos from
# the opponent's continuing range, shrinking the part of their range that
# dominates the bluff -- BLUFF_3BET_RANGE already includes A5s/A4s but also
# several broadway/suited-connector hands (KQo, KJs, QJs, JTs, T9s, 98s)
# chosen for playability, not blocker value. This flag swaps in a pure
# blocker-based set when on; does not change WHEN the bot bluff-3bets
# (still gated by BLUFF_3BET_VS_TIGHT/BLUFF_3BET_TARGET_ARCHETYPES), only
# WHICH hands it uses.
BLUFF_3BET_BLOCKER_RANGE_FLAG = False
BLUFF_3BET_BLOCKER_RANGE = {"A5s", "A4s", "A3s", "A2s", "ATo", "AJo"}

# r23 (2026-08-13, untested): published theory says a 3-bet range should be
# roughly linear (top-of-range only) from early/mid position and polarized
# (value + bluffs, skipping the middle) from late position, since late
# position already has more natural fold equity and postflop position to
# realize a bluff's equity if called. BLUFF_3BET_VS_TIGHT above only bluffs
# against a known tight/loose-aggressive raiser archetype regardless of
# hero's own position -- this flag additionally allows the bluff-3bet from
# hero's own late position against ANY opponent archetype (not just the
# targeted ones), the polarization half of the theory that's currently
# missing entirely.
THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT = True
LATE_THREEBET_BLUFF_POSITIONS = {"CO", "BTN", "SB"}

# r29 (2026-08-13, untested): published exploit advice says the best way to
# exploit a loose-passive player is to bet big for value and "exploitatively
# overfold when they show aggression" -- since a passive player raising is a
# much stronger signal than the same raise from a naturally aggressive one.
# PREMIUM_VS_3BET (facing 2+ raises) currently continues with the same
# {AA,KK,QQ,AKs,AKo} regardless of who's doing the raising. This flag folds
# the non-nut portion of that set (QQ/AKs/AKo, never AA/KK -- reuses
# FOLDABLE_PREMIUM_VS_EXTREME_AGGRO's hand set, same "never fold the actual
# nuts" floor as v26) specifically when the raiser is a known loose-passive
# archetype -- v26 already folds vs Nit/TAG on an extreme-sized bet; this is
# the mirror case (a normally-passive player suddenly 3-betting), independent
# of bet size.
FOLD_VS_3BET_FROM_PASSIVE = False  # 2026-08-15: seed42 confirmed negative (-2.15+/-1.22), seed777 had zero divergent hands in 50k -- never cross-validated. 2026-08-21 re-check post-restructure with a 300k-hand budget: ZERO divergent hands on BOTH seeds now -- confirmed untestable by self-play at the current population/model, same class as STEAL_WIDER_VS_NIT (a passive archetype 3-betting at all is too rare an OPPONENT-behavior event, not a hero-hand-filter-fixable problem).
PASSIVE_ARCHETYPES_FOR_3BET_FOLD = {"Station"}

# Candidate: defend the BB more specifically against cheap late-position
# steals. This is separate from SIZE_SCALED_CALL_RANGE because a BTN minraise
# into BB is a narrower tactical spot than "any small raise anywhere".
BB_DEFEND_VS_STEAL_MINRAISE = True
BB_DEFEND_MAX_RAISE_BB = 2.5
BB_DEFEND_VPIP_MULTIPLIER = 2.0

# r24 (2026-08-13, untested): Minimum Defense Frequency (MDF = pot / (pot +
# bet)) as an explicit floor for the BB's continuing range, instead of
# BB_DEFEND_VS_STEAL_MINRAISE's static "late-position raiser + small raise"
# gate. MDF says the cheaper the bet relative to the pot, the wider the
# whole continuing range needs to be to stay unexploitable -- this fires
# against ANY raiser position (not just LATE_STEAL_RAISER_POSITIONS) as long
# as the pot odds are cheap enough (MDF at or above the trigger), which is
# the actual published mechanism rather than a position-based proxy for it.
# Reuses bb_defend_ranges (BB_DEFEND_VPIP_MULTIPLIER) as the wide tier since
# building a fresh continuous-multiplier range per decision isn't worth the
# added complexity here -- same "a few discrete tiers, not a continuous
# function" tradeoff as every other range in this file.
BB_DEFEND_MDF_SCALED = True
BB_DEFEND_MDF_TRIGGER = 0.35  # widen when pot/(pot+bet) at or above this (a cheap-enough price)

_rankings_cache = None
_open_range_cache: dict[str, set] = {}
_call_range_cache: dict[str, set] = {}
_steal_range_cache: dict[str, set] = {}
_tight_iso_range_cache: dict[str, set] = {}
_call_range_wide_cache: dict[str, set] = {}
_call_range_narrow_cache: dict[str, set] = {}
_limp_behind_range_cache: dict[str, set] = {}
_bb_defend_range_cache: dict[str, set] = {}


def _ranges():
    global _rankings_cache, _open_range_cache, _call_range_cache, _steal_range_cache
    global _tight_iso_range_cache, _call_range_wide_cache, _call_range_narrow_cache
    global _limp_behind_range_cache, _bb_defend_range_cache
    if _rankings_cache is None:
        _rankings_cache = compute_hand_rankings()
    if not _open_range_cache:
        _open_range_cache = {
            pos: set(implied_range(vpip, _rankings_cache)) | REAL_DATA_RANGE_ADDITIONS.get(pos, set())
            for pos, vpip in OPEN_VPIP_BY_POSITION.items()
        }
    if not _call_range_cache:
        _call_range_cache = {
            pos: set(implied_range(vpip, _rankings_cache)) | REAL_DATA_CALL_RANGE_ADDITIONS.get(pos, set())
            for pos, vpip in CALL_VPIP_BY_POSITION.items()
        }
    if not _steal_range_cache:
        _steal_range_cache = {
            pos: set(implied_range(vpip, _rankings_cache)) | REAL_DATA_RANGE_ADDITIONS.get(pos, set())
            for pos, vpip in STEAL_VPIP_BY_POSITION.items()
        }
    if not _tight_iso_range_cache:
        _tight_iso_range_cache = {
            pos: set(implied_range(vpip * TIGHT_ISO_VPIP_MULTIPLIER, _rankings_cache))
            | (REAL_DATA_RANGE_ADDITIONS.get(pos, set()) if TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR else set())
            for pos, vpip in OPEN_VPIP_BY_POSITION.items()
        }
    if not _call_range_wide_cache:
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
    if not _call_range_narrow_cache:
        # 2026-08-13: previously omitted the `| REAL_DATA_CALL_RANGE_ADDITIONS`
        # union that both the base call range and the wide tier include --
        # meant the narrow tier dropped every real-population-observed calling
        # hand outright (10-20+ hands/position) on top of the VPIP shrink,
        # an unintended double-penalty likely responsible for SIZE_SCALED_
        # CALL_RANGE's measured -6.46/-5.67 bb/100 (see CLAUDE.md). Fixed to
        # match the other two tiers' construction.
        _call_range_narrow_cache = {
            pos: set(implied_range(vpip * CALL_VPIP_NARROW_MULTIPLIER, _rankings_cache)) | REAL_DATA_CALL_RANGE_ADDITIONS.get(pos, set())
            for pos, vpip in CALL_VPIP_BY_POSITION.items()
        }
    if not _limp_behind_range_cache:
        _limp_behind_range_cache = {
            pos: set(implied_range(vpip * LIMP_BEHIND_VPIP_MULTIPLIER, _rankings_cache))
            | LIMP_BEHIND_EXTRA_HANDS
            for pos, vpip in OPEN_VPIP_BY_POSITION.items()
        }
    if not _bb_defend_range_cache:
        _bb_defend_range_cache = {
            pos: set(implied_range(vpip * BB_DEFEND_VPIP_MULTIPLIER, _rankings_cache))
            | REAL_DATA_CALL_RANGE_ADDITIONS.get(pos, set())
            for pos, vpip in CALL_VPIP_BY_POSITION.items()
        }
        _bb_defend_range_cache["BB"] = (
            set(implied_range(CALL_VPIP_BY_POSITION["BTN"] * BB_DEFEND_VPIP_MULTIPLIER, _rankings_cache))
            | REAL_DATA_CALL_RANGE_ADDITIONS["BTN"]
        )
    return (
        _open_range_cache,
        _call_range_cache,
        _steal_range_cache,
        _tight_iso_range_cache,
        _call_range_wide_cache,
        _call_range_narrow_cache,
        _limp_behind_range_cache,
        _bb_defend_range_cache,
    )


_tight_iso_range_by_limpers_cache: dict[tuple[str, int], set] = {}


def _tight_iso_range_for_limpers(position: str, n_limpers: int, tight_iso_ranges: dict[str, set]) -> set | None:
    """TIGHT_ISO_TIGHTENS_PER_EXTRA_LIMPER (see the flag's comment above):
    narrow the tight-iso range further for each limper beyond the first,
    instead of only scaling sizing. Falls back to the precomputed single-
    tier `tight_iso_ranges` (cheap dict lookup) when the flag is off or
    there's only one limper -- the common case, so this stays free then."""
    if not TIGHT_ISO_TIGHTENS_PER_EXTRA_LIMPER or n_limpers <= 1:
        return tight_iso_ranges.get(position)
    global _tight_iso_range_by_limpers_cache
    key = (position, n_limpers)
    if key not in _tight_iso_range_by_limpers_cache:
        vpip = OPEN_VPIP_BY_POSITION.get(position)
        if vpip is None:
            return tight_iso_ranges.get(position)
        extra_limpers = n_limpers - 1
        multiplier = TIGHT_ISO_VPIP_MULTIPLIER * (TIGHT_ISO_EXTRA_LIMPER_STEP ** extra_limpers)
        _tight_iso_range_by_limpers_cache[key] = (
            set(implied_range(vpip * multiplier, _rankings_cache))
            | (REAL_DATA_RANGE_ADDITIONS.get(position, set()) if TIGHT_ISO_INCLUDE_REAL_DATA_FLOOR else set())
        )
    return _tight_iso_range_by_limpers_cache[key]


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


def _last_preflop_raiser_position(hand: Hand) -> str | None:
    raiser_seat = _last_preflop_raiser_seat(hand)
    return _seat_position(hand, raiser_seat) if raiser_seat is not None else None


# 2026-08-13 (r22): postflop acting order, earliest to latest -- SB acts
# first every street except preflop, BTN acts last every street including
# preflop after the first round. Used to tell whether hero will have
# position on the raiser for the rest of the hand (published theory: bigger
# 3-bet sizing out of position since OOP relies more on folds, smaller in
# position since deeper post-flop play is more available -- see CLAUDE.md's
# preflop-research notes).
POSTFLOP_ACTION_ORDER = ["SB", "BB", "UTG", "MP", "CO", "BTN"]


def _limp_trap_should_limp(player) -> bool:
    """Deterministic (not random-state-consuming, so it doesn't disturb the
    common-random-number pairing the A/B probe scripts rely on) stand-in for
    a LIMP_TRAP_FREQUENCY-ish limp rate: hashes the exact hole-card combo via
    crc32 (stable across processes, unlike Python's randomized str hash).
    With only 12 possible AA/KK combos this lands on a coarse a/12 rate, not
    a smooth LIMP_TRAP_FREQUENCY -- acceptable for an untested candidate."""
    key = ",".join(sorted(player.hole_cards)).encode()
    return (zlib.crc32(key) % 1000) / 1000.0 < LIMP_TRAP_FREQUENCY


def _is_hero_in_position_vs_raiser(hand: Hand, seat: int, raiser_seat: int) -> bool:
    hero_pos = _seat_position(hand, seat)
    raiser_pos = _seat_position(hand, raiser_seat)
    if hero_pos not in POSTFLOP_ACTION_ORDER or raiser_pos not in POSTFLOP_ACTION_ORDER:
        return False
    return POSTFLOP_ACTION_ORDER.index(hero_pos) > POSTFLOP_ACTION_ORDER.index(raiser_pos)


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

# 2026-08-20: the FIRST rule anywhere in this file to read
# opponent_freq_tiers instead of opponent_archetypes -- generalizes the
# LOOSE_ARCHETYPES any-pair-or-better call across the orthogonal axis. The
# reasoning: LOOSE_ARCHETYPES targets archetypes that bet/raise with a weak
# range on average, but postflop_freq_tier is the more DIRECT measurement
# of "does this specific opponent raise too much" -- a TAG or LAG (not in
# LOOSE_ARCHETYPES) who happens to be read as "often" is, within their own
# archetype, still overraising relative to peers, the same overextended-
# range signal LOOSE_ARCHETYPES was already a proxy for. OR'd with the
# existing archetype check (either is enough to widen), not a replacement --
# a known-loose archetype still widens the call regardless of their tier
# reading. CONFIRMED POSITIVE both seeds (scripts/probe_chance_
# enumeration.py, wider-call-vs-often-tier, --comparison current
# --adaptive): +22.27+/-7.39 (seed42) / +11.24+/-5.51 (seed777). Only
# possible to test meaningfully now that the ML opponent model has been
# retrained to actually behave differently by tier (see behavior_clone.py's
# CAT_FEATURES comment) -- before that retrain this same rule would have
# been testing noise.
WIDER_CALL_VS_OFTEN_TIER = True

# 2026-08-21/22: third rule reading a live opponent signal beyond
# archetype -- widens the same any-pair-or-better call bar against an
# aggressor currently inside their own post-cooler tilt window (any of
# acute/fading/residual -- see live_dynamics.py's COOLER_MIN_BB comment
# for the real-data finding: a player who just lost a big pot plays
# measurably looser for ~10 hands). OR'd with the archetype/freq_tier
# checks above, not a replacement.
#
# History: two early attempts (ground-truth per-hand sampling, then live
# TableTurnover-accumulated state) both showed seed42-only signals that
# turned out to be UNRELIABLE -- root cause found 2026-08-22: the
# OPPONENT bots' own choose_bot_action calls in probe_chance_
# enumeration.py never actually passed tilt_tier (only hero's ground-
# truth read via opponent_tilt_states did), so seated opponents never
# behaved differently while tilting during either of those tests -- only
# their LABEL said so, not their real modeled behavior. Fixed by wiring
# tilt_tier (and bluff_tier_a/c) into the opponents' own action calls too.
#
# RE-TESTED with the fix in place (scripts/tilt_and_bluff_confirm.sh):
# CONFIRMED POSITIVE both seeds, +2.60+/-1.06 (seed42, 34k hands, 32
# divergent) / +3.09+/-1.31 (seed777, 22k hands, 32 divergent). This is
# the first trustworthy result for this rule -- shipped True.
WIDER_CALL_VS_TILTING_OPPONENT = True

# 2026-08-22: two candidate rules for the OTHER Tier 4 idea (per-opponent
# bluff frequency) -- widens the same any-pair-or-better call bar against
# an aggressor read as a frequent bluffer (bluff_tier == "high": their
# shown aggression gets caught at real showdown more than most). Two
# independently toggleable flags, one per competing definition (see
# BLUFF_TIER_A_WEIGHTS/BLUFF_TIER_C_WEIGHTS comment above) -- built side
# by side per user's explicit "build both, compare" instruction.
#
# BOTH untestable at a 150k-hand-per-seed budget: zero divergent hands on
# BOTH seeds for BOTH variants (scripts/tilt_and_bluff_confirm.sh) --
# even variant C, whose ~30% population coverage is an order of magnitude
# better than variant A's ~2.9%. The bottleneck isn't individual coverage
# alone but the COMPOUND rarity: opponent must currently be the
# aggressor, be read as "high" bluff tier (~1/3 of the already-thin
# reliable subset), AND hero must hold exactly a hand this rule would
# change the decision for (not already covered by archetype/freq_tier/
# tilt). Variant C might resolve with a much bigger budget (1M+ hands);
# variant A likely won't at any reasonable budget. Both stay False,
# not spending more compute on this without being asked.
BLUFF_CATCH_VS_FREQUENT_BLUFFER_A = False
BLUFF_CATCH_VS_FREQUENT_BLUFFER_C = False

# 2026-08-22 (untested), Tier 6 #1: a genuinely new angle on multiway
# awareness -- stack-depth-conditioned, not frequency-conditioned (the
# three prior multiway-restriction attempts, MULTIWAY_DISABLE_AIR_CBET/
# MULTIWAY_DISABLE_LOOSE_CALL/MULTIWAY_NARROW_CALL_RANGE, all failed on
# THIS population, see their own comments -- this doesn't repeat that
# same idea a fourth time). Suppresses the LOOSE_ARCHETYPES/freq_tier/
# tilt/bluff-tier any-pair-or-better widen (see the block below) when
# ANOTHER live opponent (not the aggressor) has a short stack behind --
# a short stack changes incentives for everyone else at the table
# (side-pot dynamics, the aggressor may be betting a stronger range
# specifically because a covered short stack is already close to
# committed) that the existing archetype/tier reads don't capture.
#
# 2026-08-22 test result (scripts/tier6_confirm.sh, --comparison current
# --adaptive): ZERO divergent hands on BOTH seeds at a 150k-hand budget.
# Genuinely untestable by self-play -- same class as STEAL_WIDER_VS_NIT
# -- the compound spot (multiway + would-be-widened call + a specific
# other live opponent short-stacked) is too rare for this population/
# model to ever surface it in volume. Stays False.
MULTIWAY_TIGHTEN_VS_SHORT_STACK_BEHIND = False
SHORT_STACK_BEHIND_THRESHOLD_BB = 20.0


def _min_other_live_stack_bb(hand: Hand, seat: int, exclude: int | None) -> float | None:
    """Shortest stack (in bb) among live opponents, excluding `seat` itself
    and `exclude` (typically the current aggressor) -- None if no such
    opponent exists (heads-up or everyone else already folded)."""
    live = [s for s in _live_opponent_seats(hand, seat) if s != exclude]
    if not live or hand.big_blind <= 0:
        return None
    return min(hand.players[s].stack for s in live) / hand.big_blind


# 2026-08-22 (untested), Tier 6 #2: currently an opponent's archetype
# read is trusted identically whether it's backed by 5 hands or 5000 --
# binary "known or not," no confidence weighting by sample size. Gates
# the LOOSE_ARCHETYPES widen (see that constant's comment above) on
# having observed the aggressor for at least CONFIDENCE_MIN_HANDS hands
# THIS session (TableTurnover.hands_played_for, already tracked for
# turnover/session-length purposes -- no new infrastructure needed,
# reused as-is). When opponent_confidence isn't passed at all (the
# common case for every other test in this file), this is a pure no-op
# -- only degrades from baseline when the signal is actually present and
# still thin. CONFIDENCE_MIN_HANDS=20 is a reasonable placeholder (not
# fit to a measured breakeven point), same disclosed-guess status as
# several other thresholds in this file (e.g. SB_BIGGER_OPEN_SIZING).
# 2026-08-22 test result (scripts/confidence_gate_confirm.py -- normal
# long-adaptive-run testing doesn't work here, see that script's own
# docstring for why; uses many independent 25-hand sessions instead):
# confirmed NEGATIVE both seeds, -32.67+/-10.06 bb/100 (seed42, 5000
# hands, 86 divergent) / -29.75+/-8.64 (seed777, 5000 hands, 77
# divergent). Real, structural reason, not noise: in THIS self-play
# simulation, opponent_archetypes is always ground truth from hand 1 --
# there's no actual estimation error for "confidence" to protect
# against. Distrusting a read that's already 100% accurate can only ever
# throw away real value (falling back to the stricter top-pair-or-better
# bar against a genuinely loose aggressor for no reason), never prevent
# a mistake. This idea would need to be tested against a NOISY read
# (e.g. the live app's dossier-based style estimate, which genuinely is
# unreliable early) to have any chance of showing a real effect -- this
# probe's ground-truth-everywhere design structurally can't represent
# that. Stays False.
CONFIDENCE_GATED_ARCHETYPE_READ = False
CONFIDENCE_MIN_HANDS = 20


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


def _facing_donk_lead(hand: Hand, had_initiative: bool) -> bool:
    """True if hero (who has preflop initiative) is facing a single bet this
    street that hero did NOT fire -- an opponent without initiative led into
    the raiser instead of checking to let hero continuation-bet. Excludes
    hero facing a raise of hero's own bet (that street would already have
    2+ bets/raises recorded). Used by FOLD_MARGINAL_VS_BIG_DONK below."""
    if not had_initiative:
        return False
    return _n_bets_or_raises_this_street(hand) == 1


def _had_missed_draw(hole: list[str], board: list[str]) -> bool:
    """True if hero held a real flush/straight draw as of the turn (the
    first 4 board cards) that did NOT complete into a made hand by the
    river. Used by RIVER_BLUFF_MISSED_DRAW to keep firing a credible "the
    draw just missed" bluff story on the river instead of only ever
    checking back busted equity."""
    if len(board) < 5:
        return False
    turn_board = board[:4]
    return _has_flush_draw(hole, turn_board) or _has_straight_draw(hole, turn_board)


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


# ============================================================================
# 2026-08-14 postflop research batch (pf1-pf10). Source: CLAUDE.md's
# "2026-08-13: postflop research pass" section (~14 search queries, 100+
# sources: GTO Wizard, Upswing, PokerCoaching, Red Chip Poker, SplitSuit,
# 888poker, poker-theory forums). ALL TEN FLAGS DEFAULT FALSE. Built and
# smoke-tested for crashes only (existing 191 tests still pass unchanged,
# flipping each flag True for a short manual run threw no exceptions) --
# NONE of these have been statistically tested via scripts/
# probe_chance_enumeration.py. Treat every one as a raw, unconfirmed
# hypothesis, same status as r22-r29. Do not run the A/B validation without
# separate explicit go-ahead (see CLAUDE.md's "Never launch a batch of
# these without the user's explicit go-ahead" rule).
#
# pf2 (multiway c-bet frequency reduction) is NOT here -- it already exists
# as MULTIWAY_DISABLE_AIR_CBET above (also untested, also off), so there
# was no new code to write for it; nothing else below duplicates it.
# ============================================================================

# pf1: board-texture-dependent c-bet sizing. Published solver-approximation
# theory: dry, low-connectivity boards want a SMALL c-bet (both value and
# bluff realize their edge cheaply, and a big bet risks little extra fold
# equity for a lot more risked); wet, coordinated boards want the existing
# bigger/standard sizing (protection against equity denial, charging draws).
# Reuses `_is_wet_board` -- "dry" here is simply `not _is_wet_board(...)`, a
# disclosed two-bucket simplification, not a continuous texture score. Only
# touches the AIR c-bet (`cbet_with_air`) below, not value bets or the other
# archetype/turn/wet-board sizing rules already in this file -- those stay
# exactly as they are so this is a single, isolated variable to test.
TEXTURE_DEPENDENT_CBET_SIZING = False
DRY_CBET_POT_FRACTION = 0.33

# pf3: semi-bluff raising with a real draw, facing a bet, instead of only
# ever calling (should_call_with_draw) or folding. Published theory: raising
# a strong draw picks up folds now (fold equity this bot's calling line
# never gets) AND still has real backup equity if called -- standard modern
# strategy, especially in position. Deliberately narrow: only the flop (not
# turn -- semi-bluff-raising a turn draw commits far more with one card left,
# a bigger and separately-untested question), only a flush draw or an
# open-or-better straight draw (reuses the same `_has_flush_draw`/
# `_has_straight_draw` detectors `should_call_with_draw` already uses -- does
# NOT distinguish a strong combo draw from a bare gutshot, a known
# simplification shared with the existing call-with-draw rule), heads-up only
# (opponent-identity-ambiguity reasoning used throughout this file), and only
# when hero was NOT already the one who bet this street (raising your own
# bet makes no sense). Sizing mirrors VALUE_RAISE_MULTIPLIER's existing "3x
# the bet" convention rather than inventing a new number.
SEMI_BLUFF_RAISE_DRAWS = True
SEMI_BLUFF_RAISE_STREETS = {"flop"}
SEMI_BLUFF_RAISE_MULTIPLIER = 3.0

# 2026-08-18 (untested): the turn extension flagged as a separate open
# question above ("semi-bluff-raising a turn draw commits far more with
# one card left, a bigger and separately-untested question") -- own flag
# so flop (confirmed) and turn (not) can be confirmed/rejected
# independently rather than bundled.
SEMI_BLUFF_RAISE_DRAWS_TURN = True  # 2026-08-18: confirmed POSITIVE both seeds, +1.91+/-0.95 (seed42, 216k hands) / +2.08+/-1.04 (seed777, 218k hands). Shipped True.

# pf4: bet bigger on a board that favors hero's OWN preflop range (had
# initiative) rather than sizing purely by wet/dry texture (pf1) or opponent
# archetype (A2/v28). Published range-advantage theory: a high, dry,
# disconnected board (e.g. K-7-2 rainbow) favors the preflop raiser's range
# (more top-pair/overpair combos than a caller's range has) -- the raiser can
# size up because they're ahead more often, not just because bluffs are
# cheap there (pf1's reasoning). Simplified proxy, disclosed: "board favors
# the raiser" is approximated as (top board card >= Q) AND not
# `_is_wet_board` -- a real range-vs-range read (see
# PokerDom_Microlimits_Analysis's src/engine/range_equity.py, used by the
# live EV panel, not by this hand-coded bot) would do this properly; this is
# a cheap stand-in. Only fires on hero's own VALUE bet (`made`), only with
# initiative -- deliberately does not touch the air-cbet sizing pf1 already
# owns, to keep the two testable independently.
NUT_ADVANTAGE_SIZING = True
NUT_ADVANTAGE_MIN_TOP_RANK = "Q"
NUT_ADVANTAGE_POT_FRACTION = 0.75  # same number as BIG_VALUE_SIZING_POT_FRACTION, kept as its own constant so the two can diverge later

# 2026-08-22 (untested), Tier 6 #3: NUT_ADVANTAGE_SIZING's own comment
# above already named the honest fix -- a real range-vs-range read
# instead of the (top-card-rank, wet/dry) proxy. Turns out that engine
# already exists and is tested: PokerDom_Microlimits_Analysis's
# src/engine/range_equity.py, used by the live EV panel
# (backend/ev/live_ev.py), just never wired into this hand-coded bot's
# OWN decisions. This flag does that: replaces the proxy with a real
# Monte Carlo equity read of hero's own preflop-opening range for their
# position (open_ranges[hero_pos]) vs the single live opponent's
# implied continuing range (call_ranges[opp_pos]) on the actual board,
# and sizes up when hero's RANGE (not hero's specific hand) is
# genuinely ahead on average -- a real, continuous, board-and-position-
# aware version of "range advantage," not a binary rank/texture proxy.
# Independently toggleable from NUT_ADVANTAGE_SIZING -- only one of the
# two mechanisms should be active per test. Heads-up only (a single
# opponent's range is the only case this file already tracks a
# continuing-range table for). Kept a SEPARATE flag rather than
# replacing the confirmed original, per this file's standard practice
# of never swapping a working confirmed mechanism for an unproven one
# without its own independent confirmation first.
# 2026-08-22 test result (scripts/real_range_confirm.sh, --comparison
# current --adaptive): ZERO divergent hands on BOTH seeds at a 150k-hand
# budget each (~52 minutes total wall time -- Monte Carlo equity is
# roughly 13ms/hand here, an order of magnitude slower than most presets
# in this file). Since NUT_ADVANTAGE_SIZING (the cheap proxy) is already
# True in both arms of this comparison, divergence can only occur where
# the real equity read actively DISAGREES with the proxy's call on
# whether to size up -- and on this population, at this threshold, it
# apparently never does within 300k total hands. Real, informative
# finding: the cheap (top-card-rank, wet/dry) proxy already captures
# essentially everything the far more expensive Monte Carlo range-vs-
# range calculation would add to THIS specific binary sizing decision.
# The "honest fix" NUT_ADVANTAGE_SIZING's own original comment called
# for turned out to be unnecessary in practice. Stays False -- not
# spending more compute chasing an even bigger budget without being
# asked, given the cost-per-hand here.
REAL_RANGE_NUT_ADVANTAGE_SIZING = False
REAL_RANGE_EQUITY_THRESHOLD = 0.55
REAL_RANGE_TRIALS = 300  # kept low deliberately -- Monte Carlo equity is the single most expensive operation in this file by orders of magnitude; every trial added here multiplies the cost of every chance-enumeration probe that touches this branch

# pf5 + pf10 share one mechanism: betting a street hero did NOT bet the
# previous street, when checked to again. pf5 = hero WITHOUT initiative
# "probes" the turn after a flop that went check-check (two checks caps the
# other player's range hard, published ~31% solver-frequency source). pf10 =
# hero WITH initiative deliberately checks a marginal flop hand instead of
# firing UNCONDITIONAL_FLOP_CBET's air c-bet, then bets the turn if checked
# to again (a "delayed c-bet" -- two checks caps the OPPONENT's range the
# same way, from the aggressor's side). Both are frequency-gated via the same
# deterministic crc32 hash pattern _limp_trap_should_limp already
# established (stable across processes, doesn't consume RNG state, so it
# doesn't disturb the probe scripts' common-random-number pairing).
PROBE_BET_TURN_AFTER_CHECK = False
PROBE_BET_TURN_POT_FRACTION = 0.5
PROBE_BET_FREQUENCY = 0.5

DELAYED_CBET_MARGINAL = False
DELAYED_CBET_FREQUENCY = 0.4  # fraction of the time hero delays instead of firing the immediate UNCONDITIONAL_FLOP_CBET air c-bet
DELAYED_CBET_TURN_POT_FRACTION = 0.5


def _hole_card_frequency_roll(player, threshold: float) -> bool:
    """Same deterministic-hash pattern as _limp_trap_should_limp, generalized
    to any threshold -- crc32 of the sorted hole cards, stable across
    processes, doesn't touch Python's `random` state."""
    key = ",".join(sorted(player.hole_cards)).encode()
    return (zlib.crc32(key) % 1000) / 1000.0 < threshold


def _street_was_checked_through(hand: Hand, street: str) -> bool:
    """True if `street` happened (board is long enough) and had zero
    bets/raises on it -- i.e. everyone checked. Used by pf5/pf10 to detect
    "the previous street went check-check" from hand.actions directly,
    rather than adding new state to Hand."""
    board_len = {"flop": 3, "turn": 4, "river": 5}.get(street)
    if board_len is None or len(hand.board) < board_len:
        return False
    return not any(a.street == street and a.action in ("bets", "raises") for a in hand.actions)


def _facing_check_raise(hand: Hand, seat: int) -> bool:
    """True if the player hero is currently facing checked THIS street
    before their most recent (raising) action -- the classic check-raise
    pattern. Only meaningful when to_call > 0 and the aggressor's last
    action is a raise; used by FOLD_MARGINAL_VS_CHECK_RAISE below."""
    aggressor = _last_aggressor_this_street(hand)
    if aggressor is None:
        return False
    street_actions = [a for a in hand.actions if a.street == hand.street and a.seat == aggressor]
    if not street_actions or street_actions[-1].action != "raises":
        return False
    return any(a.action == "checks" for a in street_actions[:-1])


def _hero_called_a_bet_this_hand(hand: Hand, seat: int, street: str) -> bool:
    """True if hero has a recorded 'calls' action on the given street --
    used by FLOAT_FLOP_IN_POSITION to detect "hero floated/continued the
    flop" on a later street, without needing to reconstruct hero's exact
    hand strength at the moment of that earlier decision."""
    return any(a.street == street and a.seat == seat and a.action == "calls" for a in hand.actions)


# pf6: check back a marginal made hand for pot control instead of always
# value-betting top-pair-or-better (should_bet's `made` branch, unconditional
# today). Published theory: a plain one-pair hand, out of position, with
# 2+ live opponents, on a wet/drawy board is a classic pot-control spot --
# betting builds a pot hero doesn't want to play for stacks with a
# one-pair hand, and risks a raise hero can't profitably continue against.
# Deliberately narrow and conjunctive (all four conditions), NOT just "made
# and not very_strong" -- a plain top pair heads-up on a dry board is still
# this bot's normal, fine value bet; only the specific multiway/OOP/wet
# combination is targeted. Never overrides a genuine bluff (cbet_with_air/
# donk_bluff_with_air/barrel_bluff_with_air) or a very_strong hand.
POT_CONTROL_MARGINAL_HANDS = False


def _should_pot_control(hand: Hand, seat: int, had_initiative: bool, n_live_opps_2plus: bool) -> bool:
    if not n_live_opps_2plus:
        return False
    if had_initiative:
        return False  # OOP-without-initiative is the classic pot-control seat; IP/initiative keeps betting
    return _is_wet_board(hand.board)


# pf7: widen the postflop calling bar when stack-to-pot ratio (SPR) is
# already low -- published theory: a low SPR means hero is close to
# pot-committed regardless of hand strength, so folding a decent-but-not-
# top-pair hand (e.g. second pair, or a weak top pair) gives up equity hero
# was going to be committed to defend anyway. Effective stack is
# approximated as hero's own remaining `player.stack` (not the true
# effective = min(all live stacks) -- a disclosed simplification; this bot
# has no per-opponent stack tracking anywhere else either).
SPR_SCALED_THRESHOLDS = True
SPR_LOW_THRESHOLD = 3.0


def _effective_spr(hand: Hand, seat: int) -> float:
    pot_before = sum(p.total_contributed for p in hand.players.values())
    if pot_before <= 0:
        return float("inf")
    return hand.players[seat].stack / pot_before

# pf8: a small "block bet" river sizing tier (~25-33% pot) for thin value
# with a marginal made hand out of position, instead of either the standard
# ~55%-pot size or checking. Published theory: a block bet denies a free
# showdown-card check while risking little, specifically when hero expects
# to be ahead of a check but behind a raise/big bet -- the classic use case
# is a marginal one-pair hand, river, out of position, no initiative (the
# same "why bet small instead of big/nothing" spot pf6 also targets, but pf6
# is about NOT betting at all -- these two are mutually exclusive by
# construction below, never fire together on the same decision).
BLOCK_BET_RIVER = False
BLOCK_BET_POT_FRACTION = 0.3

# pf9: require hero's own hole cards to "block" the archetype's realistic
# calling range before firing BARREL_BLUFF_VS_TIGHT's scare-card bluff --
# published blocker theory: holding a card that removes the opponent's
# likely value combos (or that the opponent's OWN value range needs to have
# to continue) makes a bluff both less likely to run into a call and more
# likely that folded-out combos included real value. Simplified, disclosed
# proxy (no real combo-blocking calculation, which needs the range-vs-range
# machinery in PokerDom_Microlimits_Analysis's src/engine/range_equity.py,
# not duplicated here): hero holds an Ace, OR hero holds a card matching the
# scare card's own rank (removes one of the two remaining combos of whatever
# just paired/turned scary). Only narrows BARREL_BLUFF_VS_TIGHT's existing
# trigger -- never fires independently, never widens it.
BLOCKER_BASED_RIVER_BLUFF = False


def _has_river_blocker(hole: list[str], hand: Hand) -> bool:
    if any(c[0] == "A" for c in hole):
        return True
    scare_card = hand.board[-1] if hand.board else None
    return bool(scare_card) and any(c[0] == scare_card[0] for c in hole)


# 2026-08-17 (user-prompted "look closer at postflop, not every real spot is
# covered" + research check): this bot's facing-a-bet branch has never
# distinguished a check-raise from a plain bet -- `made` (top-pair-or-better)
# just calls regardless. Published low/micro-stakes strategy is specific and
# consistent here (unlike higher-stakes GTO ranges, which assume a real bluff
# mix): weak/passive-dominated fields check-raise for value far more than for
# bluffs, because most of these players' bluffs get checked instead of raised
# out of fear of being re-raised -- so a check-raise skews unusually strong,
# and the standard exploit is to fold marginal top-pair-tier hands to it more
# than to a normal bet. Deliberately excludes LOOSE_ARCHETYPES (already
# covered by the wider any-pair-or-better call rule elsewhere, which fires
# before this check ever runs) and very_strong hands (two pair+ never folds
# here regardless of the bet's shape). Heads-up only, same opponent-identity
# reasoning as every other archetype-gated rule in this file.
FOLD_MARGINAL_VS_CHECK_RAISE = False

# 2026-08-17 (same postflop-gap pass): "floating" -- calling a flop bet in
# position with no hand and no real draw, planning to bet if checked to on
# the turn -- is a real, named, published concept (Upswing/PokerCoaching/
# BetMGM strategy guides agree on the mechanism) that this bot has never had
# any version of. Distinct from pf5's probe bet (which requires a
# check-check flop, not hero calling a bet) and from pf10's delayed c-bet
# (which requires hero to have had initiative). Two parts, one flag:
#   1. Flop, facing a bet, hero has neither `made` nor a real draw (both
#      already-covered cases return before this can fire) -- call instead of
#      folding IF hero is in position against the single live opponent
#      (reuses _is_hero_in_position_vs_raiser generically, not just for the
#      preflop raiser) and that opponent isn't a known loose archetype
#      (floating doesn't work against someone who never gives up).
#   2. Turn, checked to, hero still has no hand -- bet (the "take it away"
#      follow-through), gated on hero having called a bet on the flop this
#      hand (_hero_called_a_bet_this_hand -- a disclosed proxy: doesn't
#      distinguish "floated with pure air" from "called with a draw that
#      then missed," but both are the same real bluff-the-turn decision by
#      this point, and this bot doesn't track exact historical hand strength
#      per street anywhere else either).
FLOAT_FLOP_IN_POSITION = True
FLOAT_FOLLOWUP_POT_FRACTION = 0.66  # "bet pretty large when barreling the turn" -- published sizing convention, not fit to a measured breakeven point

# 2026-08-20 (untested): generalizes FLOAT_FLOP_IN_POSITION one street later
# -- the same "a rule was restricted to one street and the restriction was
# never itself tested" pattern that produced SEMI_BLUFF_RAISE_DRAWS_TURN and
# TURN_OVERBET_NUTS_VS_LOOSE (both confirmed positive). Two parts, same
# shape as the flop version:
#   1. Turn, facing a bet, hero has neither `made` nor a real draw -- call
#      instead of folding IF in position vs the single live opponent and
#      that opponent isn't a known loose archetype. Independent of whether
#      hero also floated the flop this hand -- a turn float can start fresh
#      (e.g. hero checked back the flop with initiative, then faces a bet
#      on the turn for the first time).
#   2. River, checked to, hero still has no hand -- bet, gated on hero
#      having called a bet on the TURN this hand (not flop -- reuses
#      _hero_called_a_bet_this_hand with street="turn").
# Independently toggleable from FLOAT_FLOP_IN_POSITION -- either, both, or
# neither can be on. Needs its own A/B confirmation before shipping True.
FLOAT_TURN_IN_POSITION = True  # 2026-08-21: confirmed POSITIVE both seeds (scripts/tier5_confirm.sh, float-turn-in-position, --comparison current --adaptive), +15.76+/-7.69 (seed42) / +10.28+/-4.86 (seed777). Shipped True.

# 2026-08-17, later same day (continuing the postflop-gap audit): the three
# real gaps flagged but not closed in the overnight pass above. Same
# discipline -- researched against published sources first, built as its
# own off-by-default flag, none of this is a guess about what "should" help.

# Gap 1: no distinct response to a donk lead specifically while hero has
# preflop initiative -- `made` just calls any bet the same way regardless of
# who's betting. Published theory (PokerCoaching/Crush Live Poker et al.):
# donk-bet sizing matters a lot -- large donks (roughly 2/3 pot or bigger)
# skew meaningfully more toward real value than small ones, since a player
# donk-leading big into the raiser is usually not doing it as a cheap bluff.
# Fold a plain top-pair-tier hand (never very_strong) to a BIG donk lead
# specifically -- see _facing_donk_lead's docstring for exactly what counts.
FOLD_MARGINAL_VS_BIG_DONK = False
BIG_DONK_POT_FRACTION = 0.66

# 2026-08-22 (untested), Tier 6 #4: every bet-size-gated rule in this
# file (FOLD_MARGINAL_VS_BIG_DONK above, FOLD_TOP_PAIR_VS_OVERBET,
# FOLD_TOP_PAIR_VS_WET_BOARD_TIGHT) is a hard step function -- call
# below one fixed pot-fraction cutoff, always fold at/above it. Real
# opponents don't actually change their strategy at a single sharp
# threshold; a genuinely different mechanism is a smoothly graduated
# fold PROBABILITY that scales with bet size, applied broadly (any bet
# facing a plain top-pair-tier hand, not donk-lead-specific). Below
# CONTINUOUS_FOLD_SIZE_FLOOR (half pot) folds essentially never; at/
# above CONTINUOUS_FOLD_SIZE_CEIL (150% pot) folds up to
# CONTINUOUS_FOLD_MAX_PROB of the time, never higher -- a plain top pair
# is never abandoned entirely regardless of size. See
# _hole_card_frequency_roll's docstring for the deterministic-hash
# mechanism used to make the probability stable/reproducible per hand.
#
# 2026-08-22 test result (scripts/tier6_confirm.sh, --comparison current
# --adaptive): confirmed NEGATIVE both seeds, -0.82+/-0.33 (seed42,
# 108k hands, 30 divergent) / -0.57+/-0.22 (seed777, 112k hands, 30
# divergent). A genuinely different mechanism (graduated probability
# instead of a hard cutoff) still lands in the same place every other
# "fold more to a bigger bet" idea in this file has -- this population
# doesn't punish oversized bets the way solver-derived theory predicts,
# regardless of how the fold trigger is shaped. Stays False,
# tested-and-rejected.
CONTINUOUS_FOLD_VS_BET_SIZE = False
CONTINUOUS_FOLD_SIZE_FLOOR = 0.5
CONTINUOUS_FOLD_SIZE_CEIL = 1.5
CONTINUOUS_FOLD_MAX_PROB = 0.5

# Gap 2: `made` calls a bet the same way on a dry rainbow flop and on a
# 4-flush river -- no board-texture discount at all when calling. Published
# theory is genuinely split here: high-level guides say fold more on wet,
# highly-coordinated boards; low-stakes-specific guides warn the opposite,
# that low-stakes players over-bluff and over-folding on scary boards is a
# common losing leak, since real low-stakes ranges don't barrel wet boards
# as often as solver theory assumes. Deliberately gated to known TIGHT
# archetypes only (reusing TIGHT_ARCHETYPES_FOR_DONK_BLUFF) rather than a
# blanket rule, on the theory that a disciplined Nit/TAG/LAG betting big on
# a wet board is a much more real signal than the same bet from the loose/
# passive majority of this population -- LOOSE_ARCHETYPES already has its
# own (opposite-direction, confirmed) any-pair-or-better call rule that
# fires first and is untouched by this flag.
FOLD_TOP_PAIR_VS_WET_BOARD_TIGHT = False

# Gap 3: should_call_with_draw correctly never calls a bet with a draw on
# the river (no card left to come) -- but there was no way for hero to ever
# BET the river as a bluff specifically because a real draw just missed;
# the only existing river-bluff mechanism (BARREL_BLUFF_VS_TIGHT) requires
# a fresh scare card, not "hero personally had real outs that whiffed".
# Published theory: a missed draw is a better bluffing candidate than a
# random air hand because the betting story (drew at a hand, kept the
# pressure on) is more credible, and missed straight draws bluff better
# than missed flush draws (per Upswing's flush-draw-bluffing piece) -- not
# modeled here, both draw types are treated the same, a disclosed
# simplification matching how should_call_with_draw doesn't distinguish
# them either. Gated to known tight archetypes, same reasoning as gap 2.
RIVER_BLUFF_MISSED_DRAW = True
RIVER_BLUFF_MISSED_DRAW_POT_FRACTION = 0.66


def choose_abc_action(
    hand: Hand,
    seat: int,
    opponent_archetypes: dict[int, str] | None = None,
    opponent_freq_tiers: dict[int, str] | None = None,
    opponent_tilt_states: dict[int, str] | None = None,
    opponent_bluff_tiers_a: dict[int, str] | None = None,
    opponent_bluff_tiers_c: dict[int, str] | None = None,
    opponent_confidence: dict[int, int] | None = None,
) -> tuple[str, float | None]:
    """`opponent_archetypes`: optional {seat: archetype} for the OTHER seats
    at the table. Only used to loosen the postflop calling bar against a
    known loose/weak archetype (see LOOSE_ARCHETYPES) -- everything else in
    this bot ignores it entirely. In the live practice app this would come
    from each seat's session dossier (`dossier.style`, an estimate); the
    simulation script can also pass the ground-truth archetype to measure the
    ceiling of what opponent-awareness is worth before dossier noise.

    `opponent_freq_tiers`: optional {seat: postflop_freq_tier} ("rare"/
    "normal"/"often"), the second independent axis from the 2026-08-20
    archetype restructure. Read by WIDER_CALL_VS_OFTEN_TIER (see
    LOOSE_ARCHETYPES's comment above) -- the seated ML/population bots'
    behavior genuinely varies by tier since the 2026-08-20/21 retrain.

    `opponent_tilt_states`: optional {seat: tilt_tier} ("none"/"acute"/
    "fading"/"residual"), how many hands ago (if any) that seat lost a big
    pot -- see live_dynamics.py's COOLER_MIN_BB/POST_COOLER_WINDOW comment
    for the real-data finding behind it. Read by
    WIDER_CALL_VS_TILTING_OPPONENT (see LOOSE_ARCHETYPES's comment above).
    probe_chance_enumeration.py's _run_probe_chunk now calls
    TableTurnover.record_hand_for_tilt() after every genuinely-finished
    hand, so this reads real accumulated history within a probe run, same
    as the live app's TableTurnover tracking.

    `opponent_bluff_tiers_a`/`opponent_bluff_tiers_c`: optional {seat:
    bluff_tier} ("low"/"normal"/"high"/"unknown"), two competing
    definitions of "how often does this opponent's aggression get caught
    bluffing at real showdown" -- see live_dynamics.py's
    BLUFF_TIER_A_WEIGHTS/BLUFF_TIER_C_WEIGHTS comment for the full
    reasoning and coverage numbers. Both mostly read "unknown" for any
    given opponent.

    `opponent_confidence`: optional {seat: hands_played}, how many hands
    hero has observed this specific opponent for THIS session (see
    TableTurnover.hands_played_for). Read by
    CONFIDENCE_GATED_ARCHETYPE_READ (see LOOSE_ARCHETYPES's comment
    above) -- Tier 6's "trust an archetype read more once it's backed by
    more hands" idea."""
    (
        open_ranges,
        call_ranges,
        steal_ranges,
        tight_iso_ranges,
        call_ranges_wide,
        call_ranges_narrow,
        limp_behind_ranges,
        bb_defend_ranges,
    ) = _ranges()
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
            n_limpers = _n_limpers_preflop(hand)
            use_tight_big_iso = TIGHT_BIG_ISO_RAISE_LIMPERS and n_limpers >= 1
            use_iso_wide = ISO_WIDER_RANGE_OVER_LIMPERS and n_limpers >= 1 and not use_tight_big_iso
            if use_tight_big_iso:
                open_range = _tight_iso_range_for_limpers(position, n_limpers, tight_iso_ranges)
            else:
                open_range = steal_ranges.get(position) if (use_steal or use_iso_wide) else open_ranges.get(position)
            if open_range and notation in open_range:
                # r26 (LIMP_TRAP_WITH_MONSTERS): before the normal raise --
                # limp the very top of the range some of the time instead,
                # to set up a limp-reraise if someone raises behind. Only
                # from a genuinely unopened pot (n_limpers==0) -- limping
                # behind an existing limper is LIMP_BEHIND_OVER_LIMPERS's
                # job, a different rule with a different purpose.
                if LIMP_TRAP_WITH_MONSTERS and n_limpers == 0 and notation in LIMP_TRAP_HAND_SET and _limp_trap_should_limp(player):
                    return ("call", None)
                # v16, C1 (see ISO_RAISE_OVER_LIMPERS above): size up over
                # already-limped-in callers instead of the flat open size.
                sizing_bb = OPEN_SIZING_BB
                if use_tight_big_iso:
                    sizing_bb = TIGHT_ISO_BASE_SIZING_BB + TIGHT_ISO_SIZING_PER_LIMPER_BB * n_limpers
                elif ISO_RAISE_OVER_LIMPERS:
                    sizing_bb += ISO_SIZING_PER_LIMPER_BB * n_limpers
                # SB_BIGGER_OPEN_SIZING: see the constant's comment above --
                # only the genuine blind-vs-blind case (no limpers already
                # priced in, isolation sizing doesn't apply).
                if SB_BIGGER_OPEN_SIZING and position == "SB" and n_limpers == 0:
                    sizing_bb = SB_OPEN_SIZING_BB
                # v19, hand-strength-dependent sizing: size up further with a
                # premium hand (reuses VALUE_3BET_TIGHT as the "premium" set,
                # rather than defining a second premium-hand list) -- untested
                # theory, not read off any archetype table, opposite of the
                # usual balanced-range argument for keeping opens flat. Testing
                # it rather than assuming either direction.
                if SIZE_UP_PREMIUM_OPENS and notation in VALUE_3BET_TIGHT:
                    sizing_bb += PREMIUM_OPEN_SIZING_BONUS_BB
                # r28 (RAKE_ADJUSTED_OPEN_SIZING): smaller open from early
                # position, see the constant's comment above. Only touches
                # the plain flat-open case (not isolating a limper, which
                # already uses its own bigger sizing_bb base above).
                if RAKE_ADJUSTED_OPEN_SIZING and not use_tight_big_iso and not ISO_RAISE_OVER_LIMPERS and position in RAKE_ADJUSTED_OPEN_POSITIONS:
                    sizing_bb = RAKE_ADJUSTED_OPEN_SIZING_BB
                amount = hand.big_blind * sizing_bb
                amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
                return ("raise", amount)
            if LIMP_BEHIND_OVER_LIMPERS and n_limpers >= 1:
                limp_behind_range = limp_behind_ranges.get(position)
                if limp_behind_range and notation in limp_behind_range:
                    return ("call", None)
            return ("fold" if to_call > 0 else "check", None)

        if n_raises >= 2:
            if notation in PREMIUM_VS_3BET:
                if SHOVE_AA_KK_VS_3BET_PLUS and notation in SHOVE_VS_3BET_PLUS_RANGE:
                    if SIZED_4BET_INSTEAD_OF_SHOVE:
                        raiser_seat = _last_preflop_raiser_seat(hand)
                        in_position = raiser_seat is not None and _is_hero_in_position_vs_raiser(hand, seat, raiser_seat)
                        multiplier = SIZED_4BET_MULTIPLIER_IP if in_position else SIZED_4BET_MULTIPLIER_OOP
                        amount = hand.current_bet * multiplier
                        amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
                        return ("raise", amount)
                    return ("raise", legal["max_raise_to"])
                # v26 (see FOLD_PREMIUM_VS_EXTREME_AGGRO above): even a
                # premium hand can fold to an extreme-sized re-raise from a
                # known tight opponent -- AA/KK are the one exception that
                # never folds regardless.
                if (
                    FOLD_PREMIUM_VS_EXTREME_AGGRO
                    and notation in FOLDABLE_PREMIUM_VS_EXTREME_AGGRO
                    and opponent_archetypes
                    and player.stack > 0
                    and to_call >= EXTREME_AGGRO_STACK_FRACTION * player.stack
                ):
                    raiser_seat = _last_preflop_raiser_seat(hand)
                    raiser_archetype = opponent_archetypes.get(raiser_seat) if raiser_seat is not None else None
                    if raiser_archetype in TIGHT_ARCHETYPES_FOR_PREMIUM_FOLD:
                        return ("fold", None)
                # r29 (FOLD_VS_3BET_FROM_PASSIVE): a normally-passive player
                # 3-betting is a stronger signal than the same 3-bet from a
                # naturally aggressive one -- see the constant's comment
                # above. Checked independently of v26's bet-size gate (this
                # one's trigger is the raiser's archetype alone).
                if (
                    FOLD_VS_3BET_FROM_PASSIVE
                    and notation in FOLDABLE_PREMIUM_VS_EXTREME_AGGRO
                    and opponent_archetypes
                ):
                    raiser_seat = _last_preflop_raiser_seat(hand)
                    raiser_archetype = opponent_archetypes.get(raiser_seat) if raiser_seat is not None else None
                    if raiser_archetype in PASSIVE_ARCHETYPES_FOR_3BET_FOLD:
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
            # r22 (THREEBET_SIZE_BY_POSITION): position-dependent multiplier
            # instead of the flat THREEBET_MULTIPLIER -- see the constant's
            # comment above. No-op (returns THREEBET_MULTIPLIER) when off.
            amount = hand.current_bet * _threebet_multiplier(hand, seat)
            # v21 (SQUEEZE_SIZE_UP_PER_CALLER): size the squeeze bigger than a
            # flat 3x to actually price out the extra caller(s) -- see the
            # constant's comment above.
            if SQUEEZE_SIZE_UP_PER_CALLER:
                amount += hand.big_blind * SQUEEZE_SIZING_PER_CALLER_BB * n_callers_in
            # SIZE_UP_PREMIUM_3BETS (see the constant's comment above): the
            # same sizing bonus SIZE_UP_PREMIUM_OPENS gives a premium open,
            # applied to the value 3-bet.
            if SIZE_UP_PREMIUM_3BETS and notation in VALUE_3BET_TIGHT:
                amount += hand.big_blind * PREMIUM_3BET_SIZING_BONUS_BB
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
        # r25 (BLUFF_3BET_BLOCKER_RANGE_FLAG): swap in the blocker-based hand
        # set instead of the playability-based one -- see the constant's
        # comment above. Only changes WHICH hands bluff, not when.
        bluff_3bet_range = BLUFF_3BET_BLOCKER_RANGE if BLUFF_3BET_BLOCKER_RANGE_FLAG else BLUFF_3BET_RANGE
        if BLUFF_3BET_VS_TIGHT and opponent_archetypes:
            raiser_seat = _last_preflop_raiser_seat(hand)
            raiser_archetype = opponent_archetypes.get(raiser_seat) if raiser_seat is not None else None
            if raiser_archetype in BLUFF_3BET_TARGET_ARCHETYPES and notation in bluff_3bet_range:
                amount = hand.current_bet * _threebet_multiplier(hand, seat)
                amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
                return ("raise", amount)
        # r23 (THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT): the
        # polarization half of the published theory -- bluff-3bet from
        # hero's own late position regardless of the raiser's archetype,
        # not just against the targeted tight/loose-aggressive set above.
        # Checked after the archetype-targeted version so a known-tight
        # raiser is still handled by BLUFF_3BET_TARGET_ARCHETYPES's own
        # (already-tested) logic first; this only adds NEW bluff spots this
        # bot wouldn't otherwise take.
        if THREEBET_BLUFF_FROM_LATE_POSITION_ANY_OPPONENT and position in LATE_THREEBET_BLUFF_POSITIONS and notation in bluff_3bet_range:
            amount = hand.current_bet * _threebet_multiplier(hand, seat)
            amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
            return ("raise", amount)

        # SB_THREEBET_OR_FOLD_VS_STEAL: see the constant's comment above.
        # Only the genuine "steal" case -- a late-position raiser, hero in
        # SB -- and only reached for hands NOT already covered by the value/
        # bluff 3-bet checks above (both already `return` before this point).
        # Replaces the flat call-range check below entirely for this one
        # position+raiser-position combination: either 3-bet the extended
        # continue range, or fold -- no flat call.
        if SB_THREEBET_OR_FOLD_VS_STEAL and position == "SB":
            raiser_position = _last_preflop_raiser_position(hand)
            if raiser_position in LATE_STEAL_RAISER_POSITIONS:
                sb_continue_range = (call_ranges.get("SB") or set()) | VALUE_3BET
                if notation in sb_continue_range:
                    amount = hand.current_bet * _threebet_multiplier(hand, seat)
                    amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
                    return ("raise", amount)
                return ("fold", None)

        # SB_FOLD_VS_STEAL_DIAGNOSTIC: see the constant's comment above --
        # only meaningful (and only ever reached) when SB_THREEBET_OR_FOLD_
        # VS_STEAL is off, since that flag already returns above otherwise.
        # Deliberately targets exactly call_ranges["SB"] (not unioned with
        # VALUE_3BET the way the 3-bet-or-fold range above is) -- VALUE_3BET
        # hands already raised in the value-3-bet check further up and never
        # reach this point regardless, so unioning would be a no-op; this
        # keeps the flag's own hand set legible as "exactly what would have
        # flat-called under the normal baseline".
        if SB_FOLD_VS_STEAL_DIAGNOSTIC and position == "SB":
            raiser_position = _last_preflop_raiser_position(hand)
            if raiser_position in LATE_STEAL_RAISER_POSITIONS:
                sb_call_range = call_ranges.get("SB")
                if sb_call_range and notation in sb_call_range:
                    return ("fold", None)

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
            if CALL_RANGE_BY_RAISER_POSITION:
                raiser_position = _last_preflop_raiser_position(hand)
                if raiser_position in EARLY_RAISER_POSITIONS:
                    call_range = call_ranges_narrow.get(position)
                elif raiser_position in LATE_STEAL_RAISER_POSITIONS:
                    call_range = call_ranges_wide.get(position)
            if BB_DEFEND_VS_STEAL_MINRAISE and position == "BB":
                raiser_position = _last_preflop_raiser_position(hand)
                raise_bb = hand.current_bet / hand.big_blind if hand.big_blind else 0.0
                if raiser_position in LATE_STEAL_RAISER_POSITIONS and raise_bb <= BB_DEFEND_MAX_RAISE_BB:
                    call_range = bb_defend_ranges.get(position)
            # r24 (BB_DEFEND_MDF_SCALED): MDF-driven widening against ANY
            # raiser position, gated on pot odds instead of raiser position
            # -- see the constant's comment above. pot_before_the_bet
            # follows the same "subtract to_call from the already-inclusive
            # pot_before" pattern as FOLD_TOP_PAIR_VS_OVERBET's 2026-08-12
            # bug fix elsewhere in this file.
            if BB_DEFEND_MDF_SCALED and position == "BB" and to_call > 0:
                pot_before = sum(p.total_contributed for p in hand.players.values())
                pot_before_the_bet = pot_before - to_call
                denom = pot_before_the_bet + to_call
                mdf = pot_before_the_bet / denom if denom > 0 else 0.0
                if mdf >= BB_DEFEND_MDF_TRIGGER:
                    call_range = bb_defend_ranges.get(position)
            if call_range and notation in call_range:
                return ("call", None)
            # r27 (SET_MINE_IMPLIED_ODDS): explicit stack-depth-gated extra
            # continue for pocket pairs / suited connectors outside the
            # normal call range -- see the constant's comment above. Checked
            # only after the normal range misses, so it only ever WIDENS.
            if SET_MINE_IMPLIED_ODDS and to_call > 0:
                raiser_seat = _last_preflop_raiser_seat(hand)
                if raiser_seat is not None:
                    effective_stack = min(player.stack, hand.players[raiser_seat].stack)
                    implied_odds_multiple = (effective_stack - to_call) / to_call
                    if notation in SET_MINE_POCKET_PAIRS and implied_odds_multiple >= SET_MINE_PAIR_IMPLIED_ODDS_MULTIPLE:
                        return ("call", None)
                    if notation in SET_MINE_SUITED_CONNECTORS and implied_odds_multiple >= SET_MINE_CONNECTOR_IMPLIED_ODDS_MULTIPLE:
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
        # pf10 (DELAYED_CBET_MARGINAL): some of the time, delay the air c-bet
        # instead of firing it immediately -- see the delayed_cbet_turn
        # branch below for the follow-up bet on the turn if checked to again.
        if DELAYED_CBET_MARGINAL and cbet_with_air and not made and _hole_card_frequency_roll(player, DELAYED_CBET_FREQUENCY):
            cbet_with_air = False
        # pf5 (PROBE_BET_TURN_AFTER_CHECK): hero did NOT have preflop
        # initiative, the flop went check-check, and it's now the turn --
        # "probe" with no hand some of the time since two checks caps the
        # other player's range hard. Heads-up only (opponent-identity
        # ambiguity, same reasoning used throughout this file for every
        # other bluff trigger).
        probe_bet_turn = False
        if (
            PROBE_BET_TURN_AFTER_CHECK
            and not had_initiative
            and hand.street == "turn"
            and n_bets == 0
            and not made
            and _street_was_checked_through(hand, "flop")
            and len(_live_opponent_seats(hand, seat)) == 1
            and _hole_card_frequency_roll(player, PROBE_BET_FREQUENCY)
        ):
            probe_bet_turn = True
        # pf10, follow-up: hero HAD initiative, delayed the c-bet on the flop
        # (or would have -- this only checks the flop actually went
        # check-check, not that DELAYED_CBET_MARGINAL specifically caused
        # it, so it can also fire after an organic check-check with
        # UNCONDITIONAL_FLOP_CBET off), still has no hand, and it's now the
        # turn with nobody having bet yet. Same "two checks caps a range"
        # logic as pf5, from the aggressor's side instead of the caller's.
        delayed_cbet_turn = False
        if (
            DELAYED_CBET_MARGINAL
            and had_initiative
            and hand.street == "turn"
            and n_bets == 0
            and not made
            and _street_was_checked_through(hand, "flop")
            and len(_live_opponent_seats(hand, seat)) == 1
        ):
            delayed_cbet_turn = True
        # FLOAT_FLOP_IN_POSITION, part 2 (see the flag's comment above): hero
        # called a flop bet with air/a proxy-missed-draw, got checked to on
        # the turn -- follow through with the "take it away" bet. Deliberately
        # NOT gated on had_initiative (a float can happen whether or not hero
        # had preflop initiative -- that's the whole point, it's a
        # position-based line, not a range-based one).
        float_followup_turn = False
        if (
            FLOAT_FLOP_IN_POSITION
            and hand.street == "turn"
            and n_bets == 0
            and not made
            and len(_live_opponent_seats(hand, seat)) == 1
            and _hero_called_a_bet_this_hand(hand, seat, "flop")
        ):
            float_followup_turn = True
        # FLOAT_TURN_IN_POSITION, part 2 (see the flag's comment above): the
        # same follow-through, one street later -- hero called a turn bet
        # with air, got checked to on the river, bets. Reuses
        # _hero_called_a_bet_this_hand with street="turn" instead of "flop".
        float_followup_river = False
        if (
            FLOAT_TURN_IN_POSITION
            and hand.street == "river"
            and n_bets == 0
            and not made
            and len(_live_opponent_seats(hand, seat)) == 1
            and _hero_called_a_bet_this_hand(hand, seat, "turn")
        ):
            float_followup_river = True
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
            # pf9 (BLOCKER_BASED_RIVER_BLUFF): narrows (never widens) the
            # barrel bluff above -- only fire it if hero's own hole cards
            # also block the archetype's realistic continuing range. See
            # _has_river_blocker's docstring for the disclosed simplified
            # proxy used instead of a real combo-blocking calculation.
            if barrel_bluff_with_air and BLOCKER_BASED_RIVER_BLUFF:
                if not _has_river_blocker(player.hole_cards, hand):
                    barrel_bluff_with_air = False
        # RIVER_BLUFF_MISSED_DRAW (see the flag's comment above): fire a
        # river bluff specifically when hero's own draw just whiffed --
        # doesn't require a fresh scare card the way BARREL_BLUFF_VS_TIGHT
        # does, doesn't require had_initiative either (a caller whose draw
        # missed can tell this story too, not just the preflop raiser).
        river_bluff_missed_draw = False
        if (
            RIVER_BLUFF_MISSED_DRAW
            and hand.street == "river"
            and n_bets == 0
            and not made
            and opponent_archetypes
            and _had_missed_draw(player.hole_cards, hand.board)
        ):
            missed_draw_live_opponents = _live_opponent_seats(hand, seat)
            if len(missed_draw_live_opponents) == 1:
                if opponent_archetypes.get(missed_draw_live_opponents[0]) in TIGHT_ARCHETYPES_FOR_DONK_BLUFF:
                    river_bluff_missed_draw = True
        should_bet = made or cbet_with_air or donk_bluff_with_air or barrel_bluff_with_air or probe_bet_turn or delayed_cbet_turn or float_followup_turn or float_followup_river or river_bluff_missed_draw
        # pf6 (POT_CONTROL_MARGINAL_HANDS): check back a marginal made hand
        # instead of value-betting it, in the specific OOP/multiway/wet-board
        # spot _should_pot_control targets -- never overrides a genuine bluff
        # trigger (those aren't `made`) or a very-strong hand.
        if POT_CONTROL_MARGINAL_HANDS and made and not very_strong and should_bet:
            if _should_pot_control(hand, seat, had_initiative, n_live_opps_2plus):
                should_bet = False
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
            # pf1 (TEXTURE_DEPENDENT_CBET_SIZING): the flop air c-bet
            # specifically, sized down on a dry board -- see the flag's
            # comment above. `made` is false whenever this is the reason
            # should_bet fired, so this can't accidentally shrink a value bet.
            if TEXTURE_DEPENDENT_CBET_SIZING and cbet_with_air and not _is_wet_board(hand.board):
                sizing = DRY_CBET_POT_FRACTION
            # 2026-08-18 (SMALLER_BLUFF_ON_WET_BOARD, untested): the flip
            # side of SIZE_UP_ON_WET_BOARD -- flagged as a separate
            # untested question when v23 shipped (see that comment). A
            # pure bluff (no real hand) might want a SMALLER size on a
            # wet/coordinated board instead of the standard size, since a
            # credible story is harder to tell and more real value combos
            # exist in the opponent's continuing range there. Only touches
            # the three "plain" bluff triggers that don't already have
            # their own dedicated sizing rationale (cbet_with_air, donk_
            # bluff_with_air, barrel_bluff_with_air) -- float_followup_
            # turn/river_bluff_missed_draw keep their existing "bet big
            # when barreling" published-theory sizing untouched, a
            # different, deliberately-chosen number for a different reason.
            if (
                SMALLER_BLUFF_ON_WET_BOARD
                and not made
                and (cbet_with_air or donk_bluff_with_air or barrel_bluff_with_air)
                and _is_wet_board(hand.board)
            ):
                sizing = WET_BOARD_BLUFF_POT_FRACTION
            # pf4 (NUT_ADVANTAGE_SIZING): size up a value bet when the board
            # texture favors hero's own preflop-raiser range -- see the
            # flag's comment above for the disclosed simplified proxy.
            if (
                NUT_ADVANTAGE_SIZING
                and made
                and had_initiative
                and hand.board
                and _RANK_ORDER.index(max(c[0] for c in hand.board)) >= _RANK_ORDER.index(NUT_ADVANTAGE_MIN_TOP_RANK)
                and not _is_wet_board(hand.board)
            ):
                sizing = NUT_ADVANTAGE_POT_FRACTION
            # REAL_RANGE_NUT_ADVANTAGE_SIZING (see the flag's comment above):
            # real Monte Carlo range-vs-range equity instead of NUT_ADVANTAGE_
            # SIZING's rank/wet-dry proxy. Independently toggleable -- only
            # one of the two should be active in a given test.
            if (
                REAL_RANGE_NUT_ADVANTAGE_SIZING
                and made
                and had_initiative
                and hand.board
                and len(_live_opponent_seats(hand, seat)) == 1
            ):
                opp_seat = _live_opponent_seats(hand, seat)[0]
                hero_pos = _seat_position(hand, seat)
                opp_pos = _seat_position(hand, opp_seat)
                hero_range = open_ranges.get(hero_pos)
                opp_range = call_ranges.get(opp_pos)
                if hero_range and opp_range:
                    hero_combos = filter_combos_for_board(_expand_range(list(hero_range)), hand.board)
                    if hero_combos:
                        hero_equity, _ = combos_vs_range_equity_on_board(
                            hero_combos, list(opp_range), hand.board, trials=REAL_RANGE_TRIALS
                        )
                        if hero_equity >= REAL_RANGE_EQUITY_THRESHOLD:
                            sizing = NUT_ADVANTAGE_POT_FRACTION
            # pf8 (BLOCK_BET_RIVER): a small river sizing tier for thin value
            # with a marginal (not very_strong) made hand, out of position,
            # no initiative -- mutually exclusive with pf6's pot-control
            # check-back by construction (should_bet is already False by the
            # time we'd get here if pf6 fired, so this line is simply never
            # reached in that case).
            if BLOCK_BET_RIVER and made and not very_strong and hand.street == "river" and not had_initiative:
                sizing = BLOCK_BET_POT_FRACTION
            # pf5/pf10: the probe/delayed-c-bet turn bets have no real hand
            # (made is False) and aren't covered by any of the value-sizing
            # rules above -- give them their own fixed sizes instead of
            # silently falling through to STANDARD_SIZING_POT_FRACTION.
            if probe_bet_turn:
                sizing = PROBE_BET_TURN_POT_FRACTION
            if delayed_cbet_turn:
                sizing = DELAYED_CBET_TURN_POT_FRACTION
            if float_followup_turn:
                sizing = FLOAT_FOLLOWUP_POT_FRACTION
            if float_followup_river:
                sizing = FLOAT_FOLLOWUP_POT_FRACTION
            if river_bluff_missed_draw:
                sizing = RIVER_BLUFF_MISSED_DRAW_POT_FRACTION
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
            # 2026-08-18 (TURN_OVERBET_NUTS_VS_LOOSE): see the flag's
            # comment above -- the same overbet-with-near-nuts-vs-loose
            # idea, generalized to the turn instead of river-only.
            if (
                TURN_OVERBET_NUTS_VS_LOOSE
                and made
                and has_trips_or_better(player.hole_cards, hand.board)
                and hand.street == "turn"
                and opponent_archetypes
                and len(live_opponents) == 1
                and opponent_archetypes.get(live_opponents[0]) in LOOSE_ARCHETYPES
            ):
                sizing = TURN_OVERBET_POT_FRACTION
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
    #
    # 2026-08-12 BUG FIX: `pot_before` here is computed the same way it is
    # everywhere else in this function -- total contributed AT DECISION
    # TIME, which already includes the opponent's current bet (correct for
    # sizing hero's OWN bet as "a fraction of the pot facing me right now",
    # but wrong for "is this bet bigger than the pot WAS before it" --
    # the standard definition of "overbet"). As originally written,
    # to_call/pot_before can never exceed 1.0 for any finite bet (it's
    # bet/(pot_before_bet+bet), which approaches but never reaches 1) --
    # the condition was mathematically unreachable, confirmed by a
    # 300,000-hand probe run finding exactly zero divergent hands despite
    # real ~0.78% postflop overbet incidence measured independently.
    # Fixed by comparing against the pot as it stood BEFORE this bet
    # (pot_before - to_call).
    pot_before_the_bet = pot_before - to_call
    if made:
        if (
            FOLD_TOP_PAIR_VS_OVERBET
            and not very_strong
            and pot_before_the_bet > 0
            and (to_call / pot_before_the_bet) > OVERBET_POT_FRACTION
        ):
            # Falls straight to fold -- deliberately bypasses the
            # loose-archetype any-pair-or-better call below too, so this
            # A/B test isolates one thing (does a plain top pair fold to an
            # overbet) instead of being silently reclaimed by that other
            # rule for loose bettors specifically.
            return ("fold", None)
        # FOLD_MARGINAL_VS_CHECK_RAISE: see the flag's comment above -- a
        # plain top-pair-tier hand (never very_strong) folds to a genuine
        # check-raise specifically, against a heads-up opponent who isn't a
        # known loose archetype (that case is already served by the wider
        # any-pair call below, which never even reaches this `made` branch's
        # logic since it's a separate check further down -- but an unknown
        # or known-tight/TAG/LAG aggressor's check-raise is where this fires).
        if (
            FOLD_MARGINAL_VS_CHECK_RAISE
            and not very_strong
            and len(_live_opponent_seats(hand, seat)) == 1
            and _facing_check_raise(hand, seat)
        ):
            aggressor = _last_aggressor_this_street(hand)
            aggressor_archetype = opponent_archetypes.get(aggressor) if opponent_archetypes and aggressor is not None else None
            if aggressor_archetype not in LOOSE_ARCHETYPES:
                return ("fold", None)
        # FOLD_MARGINAL_VS_BIG_DONK: see the flag's comment above -- a plain
        # top-pair-tier hand folds to a BIG donk lead specifically, while
        # hero still holds preflop initiative.
        if (
            FOLD_MARGINAL_VS_BIG_DONK
            and not very_strong
            and pot_before_the_bet > 0
            and (to_call / pot_before_the_bet) >= BIG_DONK_POT_FRACTION
            and _facing_donk_lead(hand, had_initiative)
        ):
            return ("fold", None)
        # FOLD_TOP_PAIR_VS_WET_BOARD_TIGHT: see the flag's comment above --
        # a plain top-pair-tier hand folds to a real-sized bet on a wet
        # board specifically from a known tight archetype.
        if (
            FOLD_TOP_PAIR_VS_WET_BOARD_TIGHT
            and not very_strong
            and _is_wet_board(hand.board)
            and pot_before_the_bet > 0
            and (to_call / pot_before_the_bet) >= STANDARD_SIZING_POT_FRACTION
            and len(_live_opponent_seats(hand, seat)) == 1
        ):
            aggressor = _last_aggressor_this_street(hand)
            aggressor_archetype = opponent_archetypes.get(aggressor) if opponent_archetypes and aggressor is not None else None
            if aggressor_archetype in TIGHT_ARCHETYPES_FOR_DONK_BLUFF:
                return ("fold", None)
        # CONTINUOUS_FOLD_VS_BET_SIZE (see the flag's comment above): every
        # other bet-size-gated rule in this file is a hard step function
        # (call below a threshold, always-fold at/above it). This one
        # instead scales a plain top-pair-tier hand's fold PROBABILITY
        # smoothly with bet size -- a small overbet folds rarely, a huge
        # one folds close to CONTINUOUS_FOLD_MAX_PROB of the time, instead
        # of every size above one fixed cutoff being treated identically.
        # Applies broadly (any bet, not donk-lead-specific like
        # FOLD_MARGINAL_VS_BIG_DONK) -- a genuinely different mechanism,
        # not a parameter tweak on an already-rejected idea.
        if CONTINUOUS_FOLD_VS_BET_SIZE and not very_strong and pot_before_the_bet > 0:
            bet_frac = to_call / pot_before_the_bet
            if bet_frac > CONTINUOUS_FOLD_SIZE_FLOOR:
                span = CONTINUOUS_FOLD_SIZE_CEIL - CONTINUOUS_FOLD_SIZE_FLOOR
                fold_prob = min(1.0, (bet_frac - CONTINUOUS_FOLD_SIZE_FLOOR) / span) * CONTINUOUS_FOLD_MAX_PROB
                if _hole_card_frequency_roll(player, fold_prob):
                    return ("fold", None)
        return ("call", None)

    if (
        opponent_archetypes or opponent_freq_tiers or opponent_tilt_states or opponent_bluff_tiers_a or opponent_bluff_tiers_c
    ) and not (MULTIWAY_DISABLE_LOOSE_CALL and n_live_opps_2plus):
        aggressor = _last_aggressor_this_street(hand)
        aggressor_archetype = opponent_archetypes.get(aggressor) if opponent_archetypes and aggressor is not None else None
        aggressor_freq_tier = opponent_freq_tiers.get(aggressor) if opponent_freq_tiers and aggressor is not None else None
        aggressor_tilt = opponent_tilt_states.get(aggressor) if opponent_tilt_states and aggressor is not None else None
        aggressor_bluff_a = opponent_bluff_tiers_a.get(aggressor) if opponent_bluff_tiers_a and aggressor is not None else None
        aggressor_bluff_c = opponent_bluff_tiers_c.get(aggressor) if opponent_bluff_tiers_c and aggressor is not None else None
        aggressor_confidence = opponent_confidence.get(aggressor) if opponent_confidence and aggressor is not None else None
        archetype_trusted = (
            not CONFIDENCE_GATED_ARCHETYPE_READ or aggressor_confidence is None or aggressor_confidence >= CONFIDENCE_MIN_HANDS
        )
        is_loose_aggressor = aggressor_archetype in LOOSE_ARCHETYPES and archetype_trusted
        is_often_aggressor = WIDER_CALL_VS_OFTEN_TIER and aggressor_freq_tier == "often"
        is_tilting_aggressor = WIDER_CALL_VS_TILTING_OPPONENT and aggressor_tilt not in (None, "none")
        is_frequent_bluffer_a = BLUFF_CATCH_VS_FREQUENT_BLUFFER_A and aggressor_bluff_a == "high"
        is_frequent_bluffer_c = BLUFF_CATCH_VS_FREQUENT_BLUFFER_C and aggressor_bluff_c == "high"
        short_stack_behind = MULTIWAY_TIGHTEN_VS_SHORT_STACK_BEHIND and n_live_opps_2plus
        if short_stack_behind:
            min_other_stack = _min_other_live_stack_bb(hand, seat, exclude=aggressor)
            short_stack_behind = min_other_stack is not None and min_other_stack < SHORT_STACK_BEHIND_THRESHOLD_BB
        if (
            (is_loose_aggressor or is_often_aggressor or is_tilting_aggressor or is_frequent_bluffer_a or is_frequent_bluffer_c)
            and not short_stack_behind
            and has_any_pair_or_better(player.hole_cards, hand.board)
        ):
            return ("call", None)

    # pf7 (SPR_SCALED_THRESHOLDS): already near pot-committed (low
    # stack-to-pot ratio) -- widen the calling bar to any-pair-or-better
    # instead of folding a hand that was going to get stacked off anyway.
    # Checked before the draw logic below since it's a strictly wider bar.
    if SPR_SCALED_THRESHOLDS and _effective_spr(hand, seat) <= SPR_LOW_THRESHOLD:
        if has_any_pair_or_better(player.hole_cards, hand.board):
            return ("call", None)

    # pf3 (SEMI_BLUFF_RAISE_DRAWS): raise a strong flop draw instead of only
    # ever calling it -- see the flag's comment above for scope (flop only,
    # heads-up only, hero didn't already bet this street themselves).
    # SEMI_BLUFF_RAISE_DRAWS_TURN (2026-08-18, untested): extends the same
    # streets set to include the turn, independently toggleable.
    semi_bluff_raise_streets = SEMI_BLUFF_RAISE_STREETS | ({"turn"} if SEMI_BLUFF_RAISE_DRAWS_TURN else set())
    if (
        SEMI_BLUFF_RAISE_DRAWS
        and not made
        and hand.street in semi_bluff_raise_streets
        and (_has_flush_draw(player.hole_cards, hand.board) or _has_straight_draw(player.hole_cards, hand.board))
        and len(_live_opponent_seats(hand, seat)) == 1
    ):
        amount = hand.current_bet * SEMI_BLUFF_RAISE_MULTIPLIER
        amount = max(legal["min_raise_to"], min(legal["max_raise_to"], amount))
        return ("raise", amount)

    if should_call_with_draw(player.hole_cards, hand.board, hand.street, to_call, pot_before):
        return ("call", None)
    # FLOAT_FLOP_IN_POSITION, part 1 (see the flag's comment above): call a
    # flop bet with no hand and no real draw (both already handled above --
    # reaching here means neither applies) purely for the positional bluff
    # equity of a follow-up turn bet if checked to. Only in position against
    # a single live opponent who isn't a known loose archetype (floating
    # doesn't work against someone who never gives up the pot).
    if (
        (FLOAT_FLOP_IN_POSITION and hand.street == "flop")
        or (FLOAT_TURN_IN_POSITION and hand.street == "turn")
    ):
        float_live_opponents = _live_opponent_seats(hand, seat)
        if len(float_live_opponents) == 1:
            float_opponent = float_live_opponents[0]
            float_archetype = opponent_archetypes.get(float_opponent) if opponent_archetypes else None
            if float_archetype not in LOOSE_ARCHETYPES and _is_hero_in_position_vs_raiser(hand, seat, float_opponent):
                return ("call", None)
    return ("fold", None)
