"""Rigorous EV comparison: opening 5bb vs standard 2.5-4bb sizing, using the
actual multistreet EV engine -- not just the population frequency
description from the earlier (pre-EV-engine) pass.

Preflop response frequencies are the REAL, sizing-specific population numbers
already computed earlier this project (build_archetype_tables.py's sibling
preflop-open analysis) -- using sizing-matched frequencies here is more
relevant to this specific question than archetype-blended-across-all-sizes
stats would be. Postflop continuation uses the population-blended facing-bet
table (sizing-specific postflop data isn't available, and postflop
continuation depends mostly on the postflop bet/board, not the preflop size).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.ev.live_ev import opponent_facing_bet_stats
from src.analysis.hand_rankings import compute_hand_rankings
from src.analysis.implied_range import implied_range
from src.analysis.multistreet_ev import estimate_hand_ev, precompute_matchup

# Real, sizing-specific preflop response rates, population-wide (n-weighted
# blend of the 2.5-3bb and 3.5-4bb buckets for "standard"; the ~5bb bucket
# directly for "5bb") -- confirmed earlier this session against 841k real hands.
STANDARD_N = {"2.5-3bb": 151393, "3.5-4bb": 158217}
STANDARD_RATES = {
    "2.5-3bb": {"fold": 0.401, "call": 0.469, "threebet": 0.130},
    "3.5-4bb": {"fold": 0.454, "call": 0.428, "threebet": 0.118},
}
FIVE_BB_RATES = {"fold": 0.382, "call": 0.521, "threebet": 0.097}


def blended_standard_rates():
    total = sum(STANDARD_N.values())
    out = {}
    for key in ("fold", "call", "threebet"):
        out[key] = sum(STANDARD_RATES[b][key] * n for b, n in STANDARD_N.items()) / total
    return out


def main():
    rankings = compute_hand_rankings()
    ranges = {
        "tight (top 25%)": implied_range(0.25, rankings),
        "wide/loose (top 45%)": implied_range(0.45, rankings),
    }

    standard_rates = blended_standard_rates()
    print(f"Standard (2.5-4bb, n-weighted) preflop response: {standard_rates}")
    print(f"5bb preflop response: {FIVE_BB_RATES}")
    print()

    # Same 8-board sample the overnight batch used, for an apples-to-apples comparison.
    import random

    from src.engine.cards import RANKS, SUITS

    def sample_boards(n, seed):
        rng = random.Random(seed)
        full_deck = [r + s for r in RANKS for s in SUITS]
        return [rng.sample(full_deck, 5) for _ in range(n)]

    boards = sample_boards(6, seed=42)

    for range_label, opening_range in ranges.items():
        for sizing_label, sizing, rates in [
            ("2.5bb", 2.5, standard_rates),
            ("5bb", 5.0, FIVE_BB_RATES),
        ]:
            defender_range = implied_range(rates["call"] + rates["threebet"], rankings)
            evs = []
            for board in boards:
                matchup = precompute_matchup(
                    defender_entering_range=defender_range,
                    preflop_fold_pct=rates["fold"],
                    preflop_call_pct=rates["call"],
                    preflop_threebet_pct=rates["threebet"],
                    postflop_facing_bet={
                        s: opponent_facing_bet_stats(s, 0.55, None) for s in ("flop", "turn", "river")
                    },
                    board=board,
                    preflop_sizing_bb=sizing,
                    forward_equity_trials=150,
                )
                for hand in opening_range:
                    r = estimate_hand_ev(hand, matchup, equity_trials=600)
                    evs.append(r.ev_bb)
            avg_ev = sum(evs) / len(evs)
            print(f"range={range_label:22s} sizing={sizing_label:5s} avg EV = {avg_ev:+.3f}bb  (n={len(evs)})")


if __name__ == "__main__":
    main()
