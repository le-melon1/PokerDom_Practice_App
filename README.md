# PokerDom Practice App

Local practice tool: play NL25 6-max poker against bots trained on real
population data, with a live session-scoped opponent dossier, a live EV
panel for every decision, and a hand-coded "ABC strategy" bot you can also
play against or study.

## This is one half of a two-repo project — read this first

This app is **not self-contained**. Several core modules import directly
from the sibling [`PokerDom_Microlimits_Analysis`](https://github.com/olegvarikov/PokerDom_Microlimits_Analysis)
repo's own source tree (`backend/engine/cards_import.py`,
`backend/ev/live_ev.py`, `backend/bots/behavior_clone.py`,
`backend/bots/abc_bot.py`, `backend/solver/flop_subgame.py` all do
`from src.* import ...`), wired in via a hardcoded relative path in
`cards_import.py`. **Clone both repos as siblings under the same parent
directory, with these exact names:**

```
some-folder/
├── PokerDom_Practice_App/          (this repo)
└── PokerDom_Microlimits_Analysis/
```

If the directory names or nesting don't match, this app won't even import.

## Setup

```bash
# clone both repos into the same parent folder first (see above), then:
cd PokerDom_Practice_App
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed for scripts/browser_check.py

pytest tests/ -q               # 77 tests, should be all green
python3 run_app.py
```

Open `http://127.0.0.1:8001/` in a browser. `run_app.py` auto-resolves the
project's own `.venv` and sets `PYTHONPATH`, so it also works invoked from
outside the project directory.

## What's responsible for what

| Path | Responsibility |
|---|---|
| `backend/engine/` | Full Texas Hold'em rules engine: side pots, all-ins, rake (5%, capped 5bb, "no flop no drop" — matches the Analysis repo's `src/config.py`). Stress-tested; several real ordering/rotation bugs were found and fixed here, all covered by regression tests. |
| `backend/bots/abc_bot.py` | Hand-coded, non-ML "ABC strategy" bot. Every rule was added and then A/B-tested via `scripts/simulate_abc_bot.py` against real, measured bb/100 deltas — its own module docstring is a complete v1→v20 changelog, read that before touching the file, it explains *why* each rule exists, not just what it does. |
| `backend/bots/behavior_clone.py` | The ML opponent population: two CatBoost models (action type, sizing) trained on real hand-history decision points from the sibling repo, sampled stochastically (not argmax) so they don't play identically every time. Its docstring documents a real, measured "monster pot" bug and fix (see below). |
| `backend/bots/build_training_data.py`, `train_behavior_clone.py` | Regenerate the training parquet and the two `.cbm` model files from the Analysis repo's processed data. Not needed to just run the app — the trained models are already shipped in `data/`. |
| `backend/dossier.py` | Session-scoped opponent stats (VPIP/PFR/3-bet/aggression, position-split), reset whenever a seat's occupant turns over. |
| `backend/ev/live_ev.py` | Live equity/EV panel for the human's current decision — real Monte Carlo equity vs. an implied range, blended with each opponent's own session dossier. |
| `backend/solver/flop_subgame.py` | Outcome-sampling CFR for heads-up flop/turn subgames with blocker-aware ranges; river uses the exact showdown evaluator. Bounded sizing abstraction, not a full solve — documented in the module. |
| `backend/sessions/live_dynamics.py` | Simulates realistic table turnover: each bot's session length is bootstrap-sampled from real per-archetype session-length data, and archetype mix on re-seating is weighted by real population frequency. |
| `backend/api.py` | FastAPI routes + JSON state serialization. |
| `frontend/` | Vanilla JS/HTML UI — circular table, live EV panel, hand history, dossier view. |
| `scripts/` | One-off tools: `simulate_abc_bot.py` (80k-hand A/B testing harness with 95% CI), `diagnose_monster_pots.py` (classifies pot-inflation mechanism), `check_donk_bluff_reaction.py` (confirms ML bots can't learn within a hand), `browser_check.py`/`smoke_test_table.py` (Playwright visual checks), `generate_strategy_pdf.py`/`generate_cheatsheet_pdf.py` (produce the two PDFs at repo root). |
| `tests/` | 77 tests, pytest. |

## Data/model pipeline (why some files are shipped and some aren't)

```
Zenodo "A Dataset of Poker Hand Histories" (CC-BY 4.0, DOI 10.5281/zenodo.10796885)
  -> download separately (see the Analysis repo's README)
  -> PokerDom_Microlimits_Analysis/data/raw/**            [not in git, ~3.5G]
  -> Analysis repo's rebuild scripts
  -> PokerDom_Microlimits_Analysis/data/processed/*.parquet  [not in git, regenerate]
  -> Analysis repo's table-building scripts
  -> PokerDom_Microlimits_Analysis/data/reference/*.csv   [IN GIT, small]
  -> backend/bots/build_training_data.py (reads the Analysis repo's processed parquet)
  -> data/behavior_clone_training_data.parquet             [not in git, 370M, regenerate]
  -> backend/bots/train_behavior_clone.py
  -> data/behavior_clone_action.cbm, data/behavior_clone_sizing.cbm  [IN GIT, ready to use]
```

Practically: cloning this repo (plus its sibling) gets you a fully working
app immediately — the trained models, session-length data, and EV reference
tables are all shipped. You only need to touch the pipeline above if you
want to retrain on different/updated data.

## What's real vs. approximated

- **Game engine**: full rules, side pots, all-ins, real rake. Stress-tested
  (1500+ hands, chip conservation holds).
- **ML bots**: trained on a 1M-row sample of real decision points (the full
  dataset hit a measured non-linear CatBoost slowdown on this machine — see
  `train_behavior_clone.py`'s comments). Archetype mix on re-seating is
  weighted by real population frequency, refreshed against the current
  3.56M-hand dataset (`ARCHETYPE_POPULATION_WEIGHTS` in `live_dynamics.py`).
- **"Monster pots"**: the ML bots' sizing model has no stack-depth feature
  (a retraining attempt that added one measured *worse*, not just neutral —
  documented in `train_behavior_clone.py`), so multi-street raise
  escalation could balloon pots to unrealistic sizes. Diagnosed with real
  hand logs (`scripts/diagnose_monster_pots.py`) and fixed with progressive
  pot-based sizing damping + suppressing further raises once the legal
  min-raise increment is already large, applied to both the ML bots and the
  ABC bot's own value-bet sizing. Cut the >50bb-pot rate from ~20-24% to
  ~11%, with a real measured bb/100 improvement alongside it (see
  `behavior_clone.py`'s and `abc_bot.py`'s docstrings for the full,
  dated diagnosis and numbers).
- **Session dossier**: real counts since the current occupant sat down, no
  reliability gate, resets on seat turnover.
- **Live EV panel**: real Monte Carlo equity, but pools multiple live
  opponents into one combined range rather than a true multi-way solve —
  disclosed simplification, not a bug.
- **Trainer grading** (`backend/hand_history.py`): compares the chosen
  action against the live solver's own EV estimates and grades
  optimal/inaccuracy/mistake/blunder.

## What's still open

- **~11% of hands still exceed 50bb** even after the monster-pot fix. Some
  of that is probably legitimate deep-stack variance at this table's 100bb
  effective depth, not a residual bug — the 50bb threshold was always a
  coarse flag. The real missing feature is genuine stack-depth-aware
  sizing; a retraining attempt with stack/SPR features measured worse and
  was reverted (see `train_behavior_clone.py`).
- **ML bots architecturally cannot adapt within a session** — no
  opponent-history features at all (confirmed both by code and by a
  dedicated simulation, `scripts/check_donk_bluff_reaction.py`, p=0.44,
  flat across deciles). The Analysis repo found real players *do* show
  measurable within-session adaptation, but specifically to Nit-styled and
  frequent-bluffer opponents, not to archetypes generally — see that repo's
  README. Teaching the ML bots this one specific pattern is scoped but not
  built.
- **No persistence**: all app state (table, dossier, rake collected) lives
  in the running process's memory; restarting the server resets everything.
- **No mobile/phone access** — not started.
- A temporary debug archetype label is shown under each bot seat (hero-only)
  for testing; meant to come off once the app is out of active debugging.
