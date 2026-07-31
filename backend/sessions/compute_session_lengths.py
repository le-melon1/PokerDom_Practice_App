"""Phase B: real session-length-by-archetype distributions.

For each real table (hands.parquet's `table_name` field -- confirmed to be a
genuine, stable per-table anonymized ID, not a generic placeholder), walk its
hands in order and find each player's continuous-presence streaks. A streak
ending (player absent in the next hand at that table) = one "session" of that
length. Joined with archetype labels so bot join/leave timing can be sampled
from a real, archetype-conditioned distribution rather than guessed.

Resumable: writes one row per finished table to CSV in append mode, and skips
tables already present in that file on relaunch -- safe against an interrupted
run (e.g. the laptop losing power).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
sys.path.insert(0, str(ANALYSIS_ROOT))

import pandas as pd

from src.pipeline.archetypes import label_archetypes
from src.pipeline.preprocess import player_stats

OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "session_lengths_raw.csv"
SUMMARY_PATH = Path(__file__).resolve().parents[2] / "data" / "session_length_by_archetype.csv"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def already_done_tables() -> set:
    if not OUT_PATH.exists():
        return set()
    df = pd.read_csv(OUT_PATH, usecols=["table_name"])
    return set(df["table_name"].unique())


def compute_sessions_for_table(hand_ids: list, players_by_hand: dict) -> list[tuple[str, int]]:
    """Returns list of (player, session_length_in_hands)."""
    sessions = []
    streak_start: dict[str, int] = {}
    prev_players: set = set()

    for i, hid in enumerate(hand_ids):
        current_players = players_by_hand.get(hid, set())
        # close out streaks for players who left
        for p in prev_players - current_players:
            length = i - streak_start.pop(p, i)
            if length > 0:
                sessions.append((p, length))
        # start streaks for players who newly joined
        for p in current_players - prev_players:
            streak_start[p] = i
        prev_players = current_players

    # close remaining streaks at the end of the table's hand list
    n = len(hand_ids)
    for p, start in streak_start.items():
        length = n - start
        if length > 0:
            sessions.append((p, length))
    return sessions


def main():
    log("loading hands/actions parquet...")
    hands_df = pd.read_parquet(ANALYSIS_ROOT / "data/processed/hands.parquet")
    actions_df = pd.read_parquet(ANALYSIS_ROOT / "data/processed/actions.parquet")

    log("labeling archetypes...")
    stats = label_archetypes(player_stats(actions_df))
    archetype_by_player = dict(zip(stats["player"], stats["archetype"]))

    log("building hand_id -> players-present map...")
    players_by_hand = actions_df.groupby("hand_id")["player"].apply(set).to_dict()

    tables = hands_df[hands_df["table_name"] != ""].groupby("table_name")["hand_id"].apply(list)
    log(f"{len(tables)} real tables to process")

    done = already_done_tables()
    log(f"{len(done)} tables already done (resuming)")

    write_header = not OUT_PATH.exists()
    fh = open(OUT_PATH, "a", newline="")

    n_processed = 0
    for table_name, hand_ids in tables.items():
        if table_name in done:
            continue
        hand_ids_sorted = sorted(hand_ids)
        sessions = compute_sessions_for_table(hand_ids_sorted, players_by_hand)

        rows = pd.DataFrame(sessions, columns=["player", "session_length"])
        rows["table_name"] = table_name
        rows["archetype"] = rows["player"].map(archetype_by_player)
        rows[["table_name", "player", "archetype", "session_length"]].to_csv(
            fh, header=write_header, index=False
        )
        write_header = False
        fh.flush()

        n_processed += 1
        if n_processed % 500 == 0:
            log(f"processed {n_processed} tables")

    fh.close()
    log(f"done processing tables, total processed this run: {n_processed}")

    log("building summary by archetype...")
    raw = pd.read_csv(OUT_PATH)
    raw = raw[~raw["archetype"].isin([None, "Insufficient sample"])].dropna(subset=["archetype"])

    summary = (
        raw.groupby("archetype")["session_length"]
        .agg(["count", "mean", "median", "std", "min", "max"])
        .reset_index()
    )
    for pct in (0.1, 0.25, 0.75, 0.9):
        summary[f"p{int(pct*100)}"] = raw.groupby("archetype")["session_length"].quantile(pct).values

    summary.to_csv(SUMMARY_PATH, index=False)
    log(f"saved summary to {SUMMARY_PATH}")
    log("ALL DONE")


if __name__ == "__main__":
    main()
