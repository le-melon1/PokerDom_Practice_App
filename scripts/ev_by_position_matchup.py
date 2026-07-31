"""Extend Tier 3 to more position matchups efficiently.

The overnight batch (36 bettor-archetype x defender-archetype pairs, one
position matchup) discovered that the *bettor's* archetype doesn't actually
affect the EV number at all in this model (only the defender's range/
continuation frequencies do -- see the strategy artifact's "honest
correction"). So looping over 6 bettor archetypes was wasted compute. This
script drops that dimension: one population-blended opening range per
raiser position, times 6 defender archetypes -- 6x less work per position
matchup than the original batch, which is what makes adding more matchups
tractable in minutes instead of hours.
"""

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend.ev.live_ev import opponent_facing_bet_stats
from src.analysis.hand_rankings import compute_hand_rankings
from src.analysis.implied_range import implied_range
from src.analysis.multistreet_ev import estimate_hand_ev, precompute_matchup
from src.engine.cards import RANKS, SUITS

ARCHETYPES = ["Nit", "TAG", "LAG", "Loose-passive", "Station", "Maniac"]
N_BOARDS = 6
RANDOM_SEED = 43

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "PokerDom_Microlimits_Analysis" / "data" / "reference"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "matchup_hand_ev_by_position.csv"

# (raiser_position, defender_position) pairs to add -- BTN-vs-BB was already
# covered by the overnight batch.
MATCHUPS = [
    ("CO", "BB"),
    ("SB", "BB"),
    ("BTN", "SB"),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sample_boards(n, seed):
    import random

    rng = random.Random(seed)
    full_deck = [r + s for r in RANKS for s in SUITS]
    return [rng.sample(full_deck, 5) for _ in range(n)]


def already_done() -> set:
    if not OUT_PATH.exists():
        return set()
    df = pd.read_csv(OUT_PATH, usecols=["raiser_position", "defender_position", "defender_archetype"])
    return set(zip(df["raiser_position"], df["defender_position"], df["defender_archetype"]))


def main():
    rankings = compute_hand_rankings()
    all_hands = rankings["hand"].tolist()
    vpip_table = pd.read_csv(REFERENCE_DIR / "archetype_position_vpip.csv")
    vs_raise_table = pd.read_csv(REFERENCE_DIR / "archetype_vs_raise.csv")
    boards = sample_boards(N_BOARDS, RANDOM_SEED)

    done = already_done()
    write_header = not OUT_PATH.exists()
    fh = open(OUT_PATH, "a", newline="")
    writer = csv.writer(fh)
    if write_header:
        writer.writerow(["raiser_position", "defender_position", "defender_archetype", "hand", "avg_ev_bb"])

    for raiser_pos, defender_pos in MATCHUPS:
        raiser_rows = vpip_table[vpip_table.position == raiser_pos]
        raiser_vpip = (raiser_rows["vpip"] * raiser_rows["n_players"]).sum() / raiser_rows["n_players"].sum()
        log(f"{raiser_pos} opens (pop-blended VPIP={raiser_vpip:.3f}) vs {defender_pos} defends")

        for defender_arch in ARCHETYPES:
            if (raiser_pos, defender_pos, defender_arch) in done:
                continue
            row = vs_raise_table[(vs_raise_table.archetype == defender_arch) & (vs_raise_table.position == defender_pos)]
            if row.empty:
                log(f"  skip {defender_arch}: no vs-raise data for {defender_pos}")
                continue
            r = row.iloc[0]
            defender_range = implied_range(r["call_pct"] + r["threebet_pct"], rankings)
            postflop_stats = {s: opponent_facing_bet_stats(s, 0.55, defender_arch) for s in ("flop", "turn", "river")}

            t0 = time.time()
            hand_evs = {h: [] for h in all_hands}
            for board in boards:
                matchup = precompute_matchup(
                    defender_range,
                    preflop_fold_pct=r["fold_pct"],
                    preflop_call_pct=r["call_pct"],
                    preflop_threebet_pct=r["threebet_pct"],
                    postflop_facing_bet=postflop_stats,
                    board=board,
                    forward_equity_trials=150,
                )
                for hand in all_hands:
                    result = estimate_hand_ev(hand, matchup, equity_trials=800)
                    hand_evs[hand].append(result.ev_bb)

            for hand in all_hands:
                vals = hand_evs[hand]
                writer.writerow([raiser_pos, defender_pos, defender_arch, hand, sum(vals) / len(vals)])
            fh.flush()
            log(f"  {defender_arch} done in {time.time()-t0:.1f}s")

    fh.close()
    log("ALL DONE")


if __name__ == "__main__":
    main()
