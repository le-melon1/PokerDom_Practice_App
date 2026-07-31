# PokerDom Practice App

Local practice tool: play against bots trained on real NL25 population data
(from the sibling `PokerDom_Microlimits_Analysis` project), with a live,
session-scoped dossier per bot and a live EV panel for every decision.

## Run it

```
source .venv/bin/activate
python3 -m uvicorn backend.api:app --reload
```

Then open http://127.0.0.1:8000 in a browser.

## What's real vs. approximated

- **Game engine** (`backend/engine/`): full Texas Hold'em rules, side pots,
  all-ins. Stress-tested (1500+ hands, chip conservation holds).
- **Bots** (`backend/bots/`): two CatBoost models (action type, sizing)
  trained on 1M real decision points sampled from 841k real hands (the full
  8M-row set caused a pathological slowdown on this machine -- see
  `train_behavior_clone.py`'s comments). Bots sample from the predicted
  distribution, not argmax, so they're stochastic like real players.
- **Session dossier** (`backend/dossier.py`): VPIP/PFR/3-bet/AFq + a style
  label, counted only since the current occupant sat down -- resets when a
  bot leaves and a new one takes the seat. Shown from hand 1, no reliability
  gate (matches how the real PokerDom UI in the reference screenshot works).
- **Session-length-by-archetype** (`data/session_length_by_archetype.csv`):
  real distributions computed from the analysis project's `table_name`
  field, wired into live bot join/leave via `backend/sessions/live_dynamics.py`
  (`TableTurnover`) -- each bot's planned session length is bootstrap-sampled
  from real per-archetype session records, and it's replaced (new archetype,
  new dossier) when that count is reached or it busts. **Known gap:** the
  archetype assigned to an incoming bot is drawn uniformly at random from the
  6 archetypes, not weighted by their real population frequency (in the real
  data Loose-passive/Station are far more common than Nit/Maniac) -- so
  session *length* is honest, but the *mix* of who sits down isn't yet.
- **Live EV panel** (`backend/ev/live_ev.py`): real equity-vs-range
  computation (Monte Carlo, board-conditioned), reusing the analysis
  project's `implied_range`/`range_equity` machinery. Multiple live
  opponents are pooled into one combined range rather than resolved as a
  true multi-way solve -- documented simplification, not a bug.
- **Range CFR postflop subgame** (`backend/solver/flop_subgame.py`): heads-up
  flop and turn spots use blocker-aware hero/villain combo ranges, real chance
  cards, and outcome-sampling CFR. River uses the complete board and exact
  showdown evaluator with no chance sampling. The bounded sizing abstraction
  is minimum / 75% pot / all-in versus fold / call when checked to. Facing a
  bet, hero solves fold / call and those three raise sizes; villain can fold,
  call, or re-raise all-in, and hero then folds or calls. Investments are
  capped by the effective stack. Identical range/board/pot/stack states are
  served from a 128-entry solver LRU cache. The API also keeps the latest 64
  complete decision responses, so repeated UI refreshes of an unchanged state
  skip both solver work and the older Monte Carlo equity pipeline. Multiway and
  preflop spots continue to use the lightweight solver projection rather than
  pretending this is a full no-limit hold'em solve.
- **Trainer grading** (`backend/hand_history.py`): compares the chosen action
  and nearest available sizing with the active solver action values, reports
  EV loss immediately, and stores optimal/inaccuracy/mistake/blunder grades in
  hand history.

## Known rough edges (found and fixed this session, noted for the record)

Four real bugs were found and fixed in the engine while stress-testing:
busted players still getting dealt in and shifting the blind rotation,
wrong preflop first-to-act order, wrong postflop first-to-act order, and a
short all-in raise incorrectly lowering `current_bet` for everyone else.
All covered by regression tests in `tests/`.
